#pragma once
// بيانات جلسة التداول — سوق المال الليبي
#include <QDateTime>
#include <QString>
#include <QStringList>
#include <QVector>

struct Stock {
    QString sym, name, sector;
    double prev = 0, open = 0, high = 0, low = 0, last = 0;
    qint64 vol = 0;
    double val = 0;
    int trades = 0;
    qint64 shares = 0;   // عدد الأسهم المصدرة (0 = غير معروف)

    double chg() const { return last - prev; }
    double pct() const { return prev != 0.0 ? (last - prev) / prev * 100.0 : 0.0; }
    int dir() const { const double c = chg(); return c > 1e-4 ? 1 : (c < -1e-4 ? -1 : 0); }
    // هل جرى تداول على السهم في هذه الجلسة؟
    bool traded() const { return trades > 0 || vol > 0; }
    // متوسط سعر التنفيذ (القيمة ÷ الكمية) — 0 إذا لم يُتداول
    double vwap() const { return vol > 0 ? val / double(vol) : 0.0; }
    // القيمة السوقية بآخر سعر وبسعر الإغلاق السابق (د.ل) — 0 إذا لم يُعرف عدد الأسهم
    bool hasMcap() const { return shares > 0; }
    double mcap() const { return double(shares) * last; }
    double mcapPrev() const { return double(shares) * prev; }
};

struct SessionInfo {
    QString date;             // "2026-11-01"
    QString openT = "10:00";  // بداية التداول
    QString closeT = "13:00"; // نهاية التداول
    QString status = "auto";  // auto | open | closed
};

struct IndexInfo {
    double value = 0, prev = 0;
    QVector<double> series;   // مسار المؤشر خلال الجلسات/الجلسة
    double chg() const { return value - prev; }
    double pct() const { return prev != 0.0 ? (value - prev) / prev * 100.0 : 0.0; }
    int dir() const { const double c = chg(); return c > 1e-4 ? 1 : (c < -1e-4 ? -1 : 0); }
};

struct Totals {
    double val = 0; qint64 vol = 0; int trades = 0;
    int up = 0, down = 0, flat = 0;   // بين الشركات المتداولة فقط
    int n = 0;                        // عدد الشركات المدرجة في الملف
    int tradedN = 0;                  // عدد الشركات التي جرى عليها تداول
    double mcap = 0, mcapPrev = 0;    // القيمة السوقية الإجمالية (للشركات المعروف عدد أسهمها)
    int mcapN = 0;                    // عدد الشركات المعروف عدد أسهمها
    bool mcapComplete() const { return mcapN > 0 && mcapN == n; }
    double mcapPct() const { return mcapPrev > 0 ? (mcap - mcapPrev) / mcapPrev * 100.0 : 0.0; }
    double turnoverPct() const { return mcap > 0 ? val / mcap * 100.0 : 0.0; }   // معدل الدوران اليومي
};

struct SectorPerf {
    QString name;
    int n = 0, tradedN = 0;
    double avgPct = 0;  // تغير القطاع: مرجّح بالقيمة السوقية إن عُرفت لكل شركاته، وإلا متوسط بأوزان متساوية
    bool capWeighted = false;
    double val = 0;     // قيمة التداول
    double mcap = 0;    // القيمة السوقية للقطاع (للشركات المعروف عدد أسهمها)
    double mcapShare = 0; // حصة القطاع من القيمة السوقية للسوق (%)
    int dir() const { return avgPct > 1e-4 ? 1 : (avgPct < -1e-4 ? -1 : 0); }
};

class MarketData {
public:
    SessionInfo session;
    IndexInfo index;
    QVector<Stock> stocks;
    bool demo = true;
    QDateTime loadedAt;      // وقت آخر قراءة ناجحة
    QDateTime fileModified;  // وقت تعديل الملف المقروء

    // يقرأ من ملف JSON (data/session.json)؛ يعيد false عند الفشل مع رسالة.
    // ويدمج تلقائيًا companies.json الموجود في المجلد نفسه إن وُجد.
    bool load(const QString &path, QString *err = nullptr);
    bool loadFromJson(const QByteArray &json, QString *err = nullptr);
    // دمج الملف المرجعي companies.json: يُكمل عدد الأسهم/الاسم/القطاع الناقص (يعيد عدد الشركات التي أُكمل عدد أسهمها)
    int mergeReference(const QByteArray &json, QString *err = nullptr);
    bool mergeReferenceFile(const QString &path, QString *err = nullptr);
    void loadDefaults();     // بيانات استرشادية مدمجة
    Totals totals() const;
    QVector<SectorPerf> sectors() const;

    // فحص سلامة البيانات — يعيد قائمة تحذيرات (فارغة إذا كانت البيانات سليمة)
    QStringList validate() const;

    // ترتيب ثابت: تنازليًا بالقيمة ثم أبجديًا بالرمز (يمنع تبدّل الصفوف بين التحديثات)
    static void sortByValue(QVector<Stock> &v);
};
