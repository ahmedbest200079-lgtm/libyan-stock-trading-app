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
            {"sym":"OUT","prev":42,"last":42,"high":41,"low":41,"vol":213,"val":8733,"trades":1},
            {"sym":"VW","prev":10,"last":10,"high":10,"low":10,"vol":10,"val":500,"trades":1},
            {"sym":"OK","prev":10,"last":10}
        ]})"));
        const QStringList w = m.validate();
        auto has = [&](const QString &sym) {
            for (const QString &s : w) if (s.startsWith(sym + QStringLiteral(":"))) return true;
            return false;
        };
        QVERIFY(has(QStringLiteral("OUT")));   // آخر سعر خارج النطاق
        QVERIFY(has(QStringLiteral("VW")));    // متوسط التنفيذ 50 خارج 10–10
        QVERIFY(has(QStringLiteral("OK")));    // رمز مكرر
        QCOMPARE(w.size(), 3);
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
};

QTEST_GUILESS_MAIN(TestMarketData)
#include "test_marketdata.moc"
