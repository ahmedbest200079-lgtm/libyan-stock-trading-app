#include "MarketData.h"
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>

static Stock mk(const char *sym, const char *name, const char *sector,
                double prev, double open, double high, double low, double last,
                qint64 vol, double val, int trades)
{
    Stock s;
    s.sym = QString::fromUtf8(sym);
    s.name = QString::fromUtf8(name);
    s.sector = QString::fromUtf8(sector);
    s.prev = prev; s.open = open; s.high = high; s.low = low; s.last = last;
    s.vol = vol; s.val = val; s.trades = trades;
    return s;
}

void MarketData::loadDefaults()
{
    demo = true;
    session.date = QStringLiteral("2026-11-01");
    session.openT = QStringLiteral("10:00");
    session.closeT = QStringLiteral("13:00");
    session.status = QStringLiteral("auto");

    index.value = 1847.62;
    index.prev  = 1839.15;
    index.series = {1832.4, 1835.1, 1834.2, 1838.9, 1841.6, 1839.8, 1843.2, 1846.5, 1845.1, 1847.62};

    stocks.clear();
    stocks << mk("BTD",  "مصرف التجارة والتنمية",          "المصارف", 12.450, 12.500, 12.700, 12.450, 12.650, 148200, 1868430, 96)
           << mk("SB",   "مصرف الصحارى",                    "المصارف",  9.800,  9.800,  9.950,  9.750,  9.900,  96500,  952180, 61)
           << mk("WB",   "مصرف الوحدة",                     "المصارف",  7.350,  7.350,  7.400,  7.250,  7.300,  74300,  544210, 44)
           << mk("NCB",  "المصرف التجاري الوطني",           "المصارف", 10.200, 10.250, 10.400, 10.200, 10.350,  88900,  916470, 57)
           << mk("NAB",  "مصرف شمال أفريقيا",               "المصارف",  6.100,  6.100,  6.150,  6.000,  6.050,  51200,  310980, 28)
           << mk("ATIB", "مصرف الأمان للتجارة والاستثمار",  "المصارف",  4.750,  4.750,  4.850,  4.750,  4.850,  39800,  191230, 22)
           << mk("MED",  "مصرف المتوسط",                    "المصارف",  5.600,  5.600,  5.700,  5.550,  5.700,  46700,  263150, 31)
           << mk("SRY",  "مصرف السراي للتجارة والاستثمار",  "المصارف",  8.250,  8.200,  8.250,  8.100,  8.150,  33400,  273050, 19)
           << mk("NRN",  "مصرف النوران",                    "المصارف",  3.900,  3.900,  3.900,  3.850,  3.900,  21500,   83600, 12)
           << mk("YAQ",  "مصرف اليقين",                     "المصارف",  4.300,  4.300,  4.300,  4.200,  4.250,  18200,   77480, 11)
           << mk("LIC",  "شركة ليبيا للتأمين",              "التأمين", 14.900, 15.000, 15.250, 14.950, 15.200,  28600,  432540, 26)
           << mk("UIC",  "شركة المتحدة للتأمين",            "التأمين", 11.300, 11.300, 11.350, 11.150, 11.250,  16400,  184660, 14);
}

bool MarketData::load(const QString &path, QString *err)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) {
        if (err) *err = QStringLiteral("تعذّر فتح الملف: ") + path;
        return false;
    }
    QJsonParseError pe;
    const QJsonDocument doc = QJsonDocument::fromJson(f.readAll(), &pe);
    if (doc.isNull() || !doc.isObject()) {
        if (err) *err = QStringLiteral("صيغة JSON غير صحيحة: ") + pe.errorString();
        return false;
    }
    const QJsonObject o = doc.object();

    SessionInfo s;
    const QJsonObject so = o.value("session").toObject();
    s.date   = so.value("date").toString(session.date);
    s.openT  = so.value("openT").toString(QStringLiteral("10:00"));
    s.closeT = so.value("closeT").toString(QStringLiteral("13:00"));
    s.status = so.value("status").toString(QStringLiteral("auto"));

    IndexInfo ix;
    const QJsonObject io = o.value("index").toObject();
    ix.value = io.value("value").toDouble();
    ix.prev  = io.value("prev").toDouble();
    for (const QJsonValue &v : io.value("series").toArray())
        ix.series.append(v.toDouble());

    QVector<Stock> list;
    for (const QJsonValue &v : o.value("stocks").toArray()) {
        const QJsonObject q = v.toObject();
        Stock st;
        st.sym    = q.value("sym").toString();
        st.name   = q.value("name").toString();
        st.sector = q.value("sector").toString(QStringLiteral("أخرى"));
        st.prev   = q.value("prev").toDouble();
        st.open   = q.value("open").toDouble();
        st.high   = q.value("high").toDouble();
        st.low    = q.value("low").toDouble();
        st.last   = q.value("last").toDouble();
        st.vol    = static_cast<qint64>(q.value("vol").toDouble());
        st.val    = q.value("val").toDouble();
        st.trades = q.value("trades").toInt();
        if (!st.sym.isEmpty())
            list.append(st);
    }
    if (list.isEmpty()) {
        if (err) *err = QStringLiteral("الملف لا يحتوي قائمة أسهم (stocks)");
        return false;
    }

    session = s; index = ix; stocks = list;
    demo = o.value("demo").toBool(false);
    return true;
}

Totals MarketData::totals() const
{
    Totals t;
    t.n = stocks.size();
    for (const Stock &s : stocks) {
        t.val += s.val; t.vol += s.vol; t.trades += s.trades;
        const int d = s.dir();
        if (d > 0) ++t.up; else if (d < 0) ++t.down; else ++t.flat;
    }
    return t;
}
