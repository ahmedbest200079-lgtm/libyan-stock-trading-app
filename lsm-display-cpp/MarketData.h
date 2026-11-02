#pragma once
// بيانات جلسة التداول — سوق المال الليبي
#include <QString>
#include <QVector>

struct Stock {
    QString sym, name, sector;
    double prev = 0, open = 0, high = 0, low = 0, last = 0;
    qint64 vol = 0;
    double val = 0;
    int trades = 0;

    double chg() const { return last - prev; }
    double pct() const { return prev != 0.0 ? (last - prev) / prev * 100.0 : 0.0; }
    int dir() const { double c = chg(); return c > 1e-4 ? 1 : (c < -1e-4 ? -1 : 0); }
};

struct SessionInfo {
    QString date;            // "2026-11-01"
    QString openT = "10:00"; // بداية التداول
    QString closeT = "13:00";// نهاية التداول
    QString status = "auto"; // auto | open | closed
};

struct IndexInfo {
    double value = 0, prev = 0;
    QVector<double> series;  // مسار المؤشر خلال الجلسات/الجلسة
    double chg() const { return value - prev; }
    double pct() const { return prev != 0.0 ? (value - prev) / prev * 100.0 : 0.0; }
    int dir() const { double c = chg(); return c > 1e-4 ? 1 : (c < -1e-4 ? -1 : 0); }
};

struct Totals {
    double val = 0; qint64 vol = 0; int trades = 0;
    int up = 0, down = 0, flat = 0, n = 0;
};

class MarketData {
public:
    SessionInfo session;
    IndexInfo index;
    QVector<Stock> stocks;
    bool demo = true;

    // يقرأ من ملف JSON (data/session.json)؛ يعيد false عند الفشل مع رسالة
    bool load(const QString &path, QString *err = nullptr);
    void loadDefaults();     // بيانات استرشادية مدمجة
    Totals totals() const;
};
