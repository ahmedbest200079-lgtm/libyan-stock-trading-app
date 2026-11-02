// اختبارات نموذج بيانات الجلسة
#include <QtTest>
#include "MarketData.h"

class TestMarketData : public QObject {
    Q_OBJECT
private slots:
    void sampleFileLoads()
    {
        MarketData m;
        QString err;
        QVERIFY2(m.load(QStringLiteral(LSM_SAMPLE_JSON), &err), qPrintable(err));
        QVERIFY(!m.stocks.isEmpty());
        QVERIFY(m.index.value > 0);
    }

    void totalsCountOnlyTradedInBreadth()
    {
        MarketData m;
        QVERIFY(m.loadFromJson(R"({"stocks":[
            {"sym":"A","prev":10,"last":11,"high":11,"low":10,"vol":100,"val":1050,"trades":2},
            {"sym":"B","prev":10,"last":9,"high":9.5,"low":9,"vol":10,"val":92,"trades":1},
            {"sym":"C","prev":10,"last":10,"vol":0,"val":0,"trades":0},
            {"sym":"D","prev":10,"last":10,"high":10,"low":10,"vol":5,"val":50,"trades":1}
        ]})"));
        const Totals t = m.totals();
        QCOMPARE(t.n, 4);
        QCOMPARE(t.tradedN, 3);
        QCOMPARE(t.up, 1);
        QCOMPARE(t.down, 1);
        QCOMPARE(t.flat, 1);         // D فقط؛ C غير متداول فلا يُحسب
        QCOMPARE(t.trades, 4);
        QCOMPARE(t.vol, qint64(115));
    }

    void numbersAsStringsAccepted()
    {
        MarketData m;
        QVERIFY(m.loadFromJson(R"({"stocks":[{"sym":"x","prev":"1,250.5","last":"1260","vol":"300"}]})"));
        QCOMPARE(m.stocks[0].sym, QStringLiteral("X"));
        QCOMPARE(m.stocks[0].prev, 1250.5);
        QCOMPARE(m.stocks[0].vol, qint64(300));
    }

    void lastDefaultsToPrev()
    {
        MarketData m;
        QVERIFY(m.loadFromJson(R"({"stocks":[{"sym":"A","prev":5}]})"));
        QCOMPARE(m.stocks[0].last, 5.0);
        QCOMPARE(m.stocks[0].dir(), 0);
    }

    void invalidJsonKeepsPreviousData()
    {
        MarketData m;
        m.loadDefaults();
        const int n = m.stocks.size();
        QString err;
        QVERIFY(!m.loadFromJson("{\"stocks\": [", &err));
        QVERIFY(!err.isEmpty());
        QCOMPARE(m.stocks.size(), n);
        QVERIFY(!m.loadFromJson("{\"stocks\": []}", &err));
        QCOMPARE(m.stocks.size(), n);
    }

    void validateFlagsInconsistencies()
    {
        MarketData m;
        QVERIFY(m.loadFromJson(R"({"index":{"value":100,"prev":99},"stocks":[
            {"sym":"OK","prev":10,"last":10.5,"high":10.5,"low":10,"vol":10,"val":103,"trades":1},
            {"sym":"OUT","prev":40,"last":42,"high":41,"low":41,"vol":213,"val":8733,"trades":1},
            {"sym":"HELD","prev":42,"last":42,"high":41,"low":41,"vol":213,"val":8733,"trades":1},
            {"sym":"VW","prev":10,"last":10,"high":10,"low":10,"vol":10,"val":500,"trades":1},
            {"sym":"OK","prev":10,"last":10}
        ]})"));
        const QStringList w = m.validate();
        auto has = [&](const QString &sym) {
            for (const QString &s : w) if (s.startsWith(sym + QStringLiteral(":"))) return true;
            return false;
        };
        QVERIFY(has(QStringLiteral("OUT")));   // سعر الإغلاق تغيّر إلى خارج النطاق ← خطأ
        QVERIFY(!has(QStringLiteral("HELD"))); // سعر الإغلاق لم يتغير (لم يستوفِ شرط التغيير) ← مقبول
        QVERIFY(has(QStringLiteral("VW")));    // متوسط التنفيذ 50 خارج 10–10
        QVERIFY(has(QStringLiteral("OK")));    // رمز مكرر
        QCOMPARE(w.size(), 3);   // OUT + VW + OK المكرر
    }

    void closeHeldAndBidAsk()
    {
        MarketData m;
        QVERIFY(m.loadFromJson(R"({"index":{"value":1134.57,"prev":1139.04,"high":1139.04,"low":1134.57},"stocks":[
            {"sym":"BCD","prev":42,"open":42,"high":41,"low":41,"last":42,"vol":213,"val":8733,"trades":1,"bid":39,"ask":41},
            {"sym":"X","prev":10,"last":10,"bid":11,"ask":10.5}
        ]})"));
        QVERIFY(m.stocks[0].closeHeld());
        QCOMPARE(m.stocks[0].bid, 39.0);
        QCOMPARE(m.stocks[0].ask, 41.0);
        QCOMPARE(m.index.high, 1139.04);
        const QStringList w = m.validate();
        QCOMPARE(w.size(), 1);
        QVERIFY(w[0].startsWith(QStringLiteral("X:")));   // طلب أعلى من عرض
    }

    void officialSessionMarketCapMatchesReport()
    {
        // ملف الجلسة المولّد من التقرير الرسمي 2026-11-01: إجمالي القيمة السوقية في التقرير 11,268,446,000
        MarketData m;
        QVERIFY(m.load(QStringLiteral(LSM_SAMPLE_JSON)));
        const Totals t = m.totals();
        QVERIFY(t.mcapComplete());
        QCOMPARE(qRound64(t.mcap), Q_INT64_C(11268446000));
        QVERIFY(qAbs(t.val - 75118.3) < 1e-6);
        QCOMPARE(t.tradedN, 3);
        QCOMPARE(t.up, 0); QCOMPARE(t.down, 1); QCOMPARE(t.flat, 2);
        for (const SectorPerf &p : m.sectors()) {
            QVERIFY(p.capWeighted);
            if (p.name == QStringLiteral("المصارف")) QCOMPARE(qRound64(p.mcap), Q_INT64_C(10981056000));
            if (p.name == QStringLiteral("التأمين")) QCOMPARE(qRound64(p.mcap), Q_INT64_C(135890000));
        }
        QVERIFY(m.validate().isEmpty());
    }

    void stableSortByValueThenSymbol()
    {
        QVector<Stock> v(3);
        v[0].sym = "C"; v[1].sym = "A"; v[2].sym = "B"; v[2].val = 5;
        MarketData::sortByValue(v);
        QCOMPARE(v[0].sym, QStringLiteral("B"));
        QCOMPARE(v[1].sym, QStringLiteral("A"));
        QCOMPARE(v[2].sym, QStringLiteral("C"));
    }

    void sectorsEqualWeighted()
    {
        MarketData m;
        QVERIFY(m.loadFromJson(R"({"stocks":[
            {"sym":"A","sector":"S1","prev":10,"last":11,"vol":1,"val":11,"trades":1},
            {"sym":"B","sector":"S1","prev":10,"last":10},
            {"sym":"C","sector":"S2","prev":10,"last":9,"vol":1,"val":9,"trades":1}
        ]})"));
        const QVector<SectorPerf> s = m.sectors();
        QCOMPARE(s.size(), 2);
        QCOMPARE(s[0].name, QStringLiteral("S1"));
        QCOMPARE(s[0].n, 2);
        QCOMPARE(s[0].tradedN, 1);
        QVERIFY(qAbs(s[0].avgPct - 5.0) < 1e-9);
        QVERIFY(qAbs(s[1].avgPct + 10.0) < 1e-9);
    }

    void marketCapTotalsAndCoverage()
    {
        MarketData m;
        QVERIFY(m.loadFromJson(R"({"stocks":[
            {"sym":"A","prev":10,"last":11,"vol":100,"val":1050,"trades":1,"shares":1000000},
            {"sym":"B","prev":20,"last":20,"shares":"500,000"},
            {"sym":"C","prev":5,"last":5}
        ]})"));
        const Totals t = m.totals();
        QCOMPARE(t.mcapN, 2);
        QVERIFY(!t.mcapComplete());
        QCOMPARE(t.mcap, 11e6 + 10e6);
        QCOMPARE(t.mcapPrev, 10e6 + 10e6);
        QVERIFY(qAbs(t.mcapPct() - 5.0) < 1e-9);
        QVERIFY(qAbs(t.turnoverPct() - 1050.0 / 21e6 * 100.0) < 1e-12);
    }

    void sectorCapWeightedWhenAllSharesKnown()
    {
        MarketData m;
        QVERIFY(m.loadFromJson(R"({"stocks":[
            {"sym":"BIG","sector":"S","prev":10,"last":11,"shares":9000000},
            {"sym":"SML","sector":"S","prev":10,"last":9,"shares":1000000},
            {"sym":"X","sector":"T","prev":10,"last":11,"shares":1000000},
            {"sym":"Y","sector":"T","prev":10,"last":10}
        ]})"));
        const QVector<SectorPerf> s = m.sectors();
        QVERIFY(s[0].capWeighted);
        QVERIFY(qAbs(s[0].avgPct - 8.0) < 1e-9);        // (99+9-100)/100 = 8% مقابل 0% بأوزان متساوية
        QVERIFY(!s[1].capWeighted);                       // Y بلا عدد أسهم ← أوزان متساوية
        QVERIFY(qAbs(s[1].avgPct - 5.0) < 1e-9);
        QVERIFY(qAbs(s[0].mcapShare - 108.0 / 119.0 * 100.0) < 1e-9);
    }

    void referenceFillsMissingShares()
    {
        MarketData m;
        QVERIFY(m.loadFromJson(R"({"stocks":[
            {"sym":"A","prev":10,"last":10},
            {"sym":"B","prev":10,"last":10,"shares":5}
        ]})"));
        const int n = m.mergeReference(R"({"companies":[
            {"sym":"a","shares":1000,"sector":"S1"},
            {"sym":"B","shares":999},
            {"sym":"Z","shares":1}
        ]})");
        QCOMPARE(n, 1);
        QCOMPARE(m.stocks[0].shares, qint64(1000));
        QCOMPARE(m.stocks[0].sector, QStringLiteral("S1"));
        QCOMPARE(m.stocks[1].shares, qint64(5));          // القيمة في ملف الجلسة لها الأولوية
        QCOMPARE(m.stocks.size(), 2);                     // لا تُضاف شركة بلا سعر
    }

    void sampleReferenceFileIsValid()
    {
        MarketData m;
        QVERIFY(m.load(QStringLiteral(LSM_SAMPLE_JSON)));
        QFile f(QFileInfo(QStringLiteral(LSM_SAMPLE_JSON)).dir().filePath("companies.json"));
        QVERIFY(f.open(QIODevice::ReadOnly));
        QVERIFY(m.mergeReference(f.readAll()) >= 0);
    }
};

QTEST_GUILESS_MAIN(TestMarketData)
#include "test_marketdata.moc"
