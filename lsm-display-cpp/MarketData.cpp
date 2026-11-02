#include "MarketData.h"
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMap>
#include <QSet>
#include <algorithm>
#include <cmath>

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
    session.date = QDate::currentDate().toString(Qt::ISODate);
    session.openT = QStringLiteral("10:00");
    session.closeT = QStringLiteral("13:00");
    session.status = QStringLiteral("auto");

    index.value = 1847.62;
    index.prev  = 1839.15;
    index.series = {1839.15, 1835.1, 1834.2, 1838.9, 1841.6, 1839.8, 1843.2, 1846.5, 1845.1, 1847.62};

    stocks.clear();
    stocks << mk("BCD",  "مصرف التجارة والتنمية",          "المصارف", 12.450, 12.500, 12.700, 12.450, 12.650, 148200, 1868430, 96)
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
    loadedAt = QDateTime::currentDateTime();
    fileModified = QDateTime();
}

// يقبل الرقم سواء كُتب رقمًا أو نصًا ("12.5" أو "1,250") — تحمّلًا لاختلاف منظومات التغذية
static double num(const QJsonValue &v, double def = 0.0)
{
    if (v.isDouble()) return v.toDouble();
    if (v.isString()) {
        QString s = v.toString().trimmed();
        s.remove(QLatin1Char(','));
        bool ok = false;
        const double d = s.toDouble(&ok);
        return ok ? d : def;
    }
    return def;
}

bool MarketData::load(const QString &path, QString *err)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) {
        if (err) *err = QStringLiteral("تعذّر فتح الملف: ") + path;
        return false;
    }
    if (!loadFromJson(f.readAll(), err))
        return false;
    fileModified = QFileInfo(path).lastModified();
    return true;
}

bool MarketData::loadFromJson(const QByteArray &json, QString *err)
{
    QJsonParseError pe;
    const QJsonDocument doc = QJsonDocument::fromJson(json, &pe);
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
    s.status = so.value("status").toString(QStringLiteral("auto")).trimmed().toLower();

    IndexInfo ix;
    const QJsonObject io = o.value("index").toObject();
    ix.value = num(io.value("value"));
    ix.prev  = num(io.value("prev"));
    for (const QJsonValue &v : io.value("series").toArray())
        ix.series.append(num(v));

    QVector<Stock> list;
    for (const QJsonValue &v : o.value("stocks").toArray()) {
        const QJsonObject q = v.toObject();
        Stock st;
        st.sym    = q.value("sym").toString().trimmed().toUpper();
        st.name   = q.value("name").toString().trimmed();
        st.sector = q.value("sector").toString().trimmed();
        if (st.sector.isEmpty()) st.sector = QStringLiteral("أخرى");
        if (st.name.isEmpty()) st.name = st.sym;
        st.prev   = num(q.value("prev"));
        st.last   = num(q.value("last"), st.prev);
        st.open   = num(q.value("open"));
        st.high   = num(q.value("high"));
        st.low    = num(q.value("low"));
        st.vol    = static_cast<qint64>(std::llround(num(q.value("vol"))));
        st.val    = num(q.value("val"));
        st.trades = static_cast<int>(std::lround(num(q.value("trades"))));
        if (!st.sym.isEmpty())
            list.append(st);
    }
    if (list.isEmpty()) {
        if (err) *err = QStringLiteral("الملف لا يحتوي قائمة أسهم (stocks)");
        return false;
    }

    session = s; index = ix; stocks = list;
    demo = o.value("demo").toBool(false);
    loadedAt = QDateTime::currentDateTime();
    return true;
}

Totals MarketData::totals() const
{
    Totals t;
    t.n = stocks.size();
    for (const Stock &s : stocks) {
        t.val += s.val; t.vol += s.vol; t.trades += s.trades;
        if (!s.traded()) continue;   // الأسهم غير المتداولة لا تدخل في الاتساع
        ++t.tradedN;
        const int d = s.dir();
        if (d > 0) ++t.up; else if (d < 0) ++t.down; else ++t.flat;
    }
    return t;
}

QVector<SectorPerf> MarketData::sectors() const
{
    QMap<QString, SectorPerf> map;
    QMap<QString, double> sumPct;
    QStringList order;                 // بترتيب ظهور القطاع في الملف
    for (const Stock &s : stocks) {
        if (!map.contains(s.sector)) { order << s.sector; map[s.sector].name = s.sector; }
        SectorPerf &a = map[s.sector];
        ++a.n;
        if (s.traded()) ++a.tradedN;
        a.val += s.val;
        sumPct[s.sector] += s.pct();
    }
    QVector<SectorPerf> out;
    for (const QString &k : order) {
        SectorPerf p = map.value(k);
        p.avgPct = p.n > 0 ? sumPct.value(k) / p.n : 0.0;
        out << p;
    }
    return out;
}

void MarketData::sortByValue(QVector<Stock> &v)
{
    std::stable_sort(v.begin(), v.end(), [](const Stock &a, const Stock &b) {
        if (a.val != b.val) return a.val > b.val;
        return a.sym < b.sym;
    });
}

QStringList MarketData::validate() const
{
    QStringList w;
    const double eps = 1e-6;
    QSet<QString> seen;
    for (const Stock &s : stocks) {
        const QString tag = s.sym + QStringLiteral(": ");
        if (seen.contains(s.sym)) w << tag + QStringLiteral("رمز مكرر");
        seen.insert(s.sym);
        if (s.prev <= 0) w << tag + QStringLiteral("سعر الإغلاق السابق غير صالح");
        if (s.last <= 0) w << tag + QStringLiteral("آخر سعر غير صالح");
        if (s.vol < 0 || s.val < 0 || s.trades < 0) w << tag + QStringLiteral("قيم تداول سالبة");

        if (s.traded()) {
            if (s.high <= 0 || s.low <= 0)
                w << tag + QStringLiteral("متداول دون أعلى/أدنى سعر");
            else if (s.high + eps < s.low)
                w << tag + QStringLiteral("الأعلى أقل من الأدنى");
            else if (s.last > s.high + eps || s.last < s.low - eps) {
                // ملاحظة: قد يكون مقصودًا إن لم يستوفِ التداول شرط تغيير سعر الإغلاق
                w << tag + QStringLiteral("آخر سعر خارج نطاق الأعلى/الأدنى");
            }
            if (s.val <= 0 && s.vol > 0)
                w << tag + QStringLiteral("كمية بلا قيمة");
            else if (s.vol > 0 && s.high > 0 && s.low > 0) {
                const double vw = s.vwap();
                if (vw > s.high * 1.005 || vw < s.low * 0.995)
                    w << tag + QStringLiteral("متوسط التنفيذ (القيمة÷الكمية) خارج النطاق");
            }
            if (s.trades <= 0 && s.vol > 0)
                w << tag + QStringLiteral("كمية بلا صفقات");
        }
    }
    if (index.prev <= 0 || index.value <= 0)
        w << QStringLiteral("قيمة المؤشر غير صالحة");
    return w;
}
