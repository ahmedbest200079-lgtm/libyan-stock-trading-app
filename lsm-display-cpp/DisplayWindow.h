#pragma once
// النافذة الرئيسية لشاشة عرض أسهم سوق المال الليبي — كل اللوحات في شاشة واحدة
#include <QDateTime>
#include <QMainWindow>
#include "MarketData.h"

class QLabel;
class QTableWidget;
class QTimer;
class QHBoxLayout;
class QFrame;

// خيارات التشغيل (من سطر الأوامر)
struct DisplayOptions {
    QString dataPath;            // مسار ملف البيانات (افتراضيًا data/session.json بجوار البرنامج)
    bool fullscreen = false;     // بدء التشغيل في وضع القاعة (ملء الشاشة)
    int pollMs = 5000;           // فترة فحص تعديل الملف
    int staleMinutes = 10;       // تنبيه إن لم يُحدَّث الملف أثناء الجلسة خلال هذه المدة
    int pageSeconds = 8;         // فترة التمرير الآلي لجدول الأسعار عند زيادة الشركات عن مساحة الشاشة
    QString snapshotPath;        // إن حُدّد: تُحفظ صورة للشاشة ثم يُغلق البرنامج
};

// ── شريط الأسعار المتحرك ──
class TickerWidget : public QWidget {
    Q_OBJECT
public:
    explicit TickerWidget(QWidget *parent = nullptr);
    void setData(const QVector<Stock> &stocks);
    QSize sizeHint() const override;
protected:
    void paintEvent(QPaintEvent *) override;
private:
    struct Item { QString sym, price, pct; int dir; bool traded; };
    QVector<Item> m_items;
    qreal m_offset = 0;
    QTimer *m_timer;
};

// ── رسم بياني مصغّر للمؤشر ──
class SparklineWidget : public QWidget {
    Q_OBJECT
public:
    explicit SparklineWidget(QWidget *parent = nullptr);
    void setSeries(const QVector<double> &s, double baseline, int dir);
    QSize sizeHint() const override;
protected:
    void paintEvent(QPaintEvent *) override;
private:
    QVector<double> m_series;
    double m_base = 0;
    int m_dir = 0;
};

// ── شريط الصاعد/المستقر/الهابط ──
class BreadthBar : public QWidget {
    Q_OBJECT
public:
    explicit BreadthBar(QWidget *parent = nullptr);
    void setCounts(int up, int flat, int down);
    QSize sizeHint() const override;
protected:
    void paintEvent(QPaintEvent *) override;
private:
    int m_up = 0, m_flat = 0, m_down = 0;
};

// ── النافذة الرئيسية ──
class DisplayWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit DisplayWindow(const DisplayOptions &opt, QWidget *parent = nullptr);
    void start();                 // العرض حسب الخيارات (عادي/ملء الشاشة/لقطة)
public slots:
    void reloadData(bool force = false);
protected:
    void keyPressEvent(QKeyEvent *e) override;
    bool eventFilter(QObject *o, QEvent *e) override;
private slots:
    void tickClock();
    void pageTable();
private:
    void buildUi();
    void renderAll();
    void renderHeader();
    void renderIndex();
    void renderStats();
    void renderTable();
    void renderMovers();
    void renderBottom();
    void renderNote();
    void fitRows();
    void setHall(bool on);
    bool sessionOpenNow(const QDateTime &now) const;

    DisplayOptions m_opt;
    MarketData m_data;
    QString m_loadError;          // آخر خطأ قراءة (تبقى البيانات السابقة معروضة)
    QStringList m_warnings;       // تحذيرات فحص سلامة البيانات
    QString m_sig;                // بصمة ملفي البيانات والمرجع (وقت التعديل + الحجم)
    QString filesSig() const;

    TickerWidget   *m_ticker = nullptr;
    QLabel         *m_sessDate = nullptr, *m_clock = nullptr, *m_status = nullptr, *m_note = nullptr;
    QLabel         *m_idxVal = nullptr, *m_idxChg = nullptr, *m_idxSub = nullptr;
    SparklineWidget*m_spark = nullptr;
    QLabel         *m_stVal = nullptr, *m_stVol = nullptr, *m_stTr = nullptr, *m_stN = nullptr, *m_stBreadthLbl = nullptr,
                   *m_stCap = nullptr, *m_stCapSub = nullptr;
    BreadthBar     *m_breadth = nullptr;
    QTableWidget   *m_table = nullptr;
    QFrame         *m_upCard = nullptr, *m_dnCard = nullptr, *m_acCard = nullptr;
    QHBoxLayout    *m_heatRow = nullptr;     // صف خريطة السوق أسفل الشاشة
    QHBoxLayout    *m_sectorsRow = nullptr;  // سطر القطاعات

    QTimer *m_clockTimer = nullptr, *m_reloadTimer = nullptr, *m_pageTimer = nullptr;
    bool m_hall = false;
};
