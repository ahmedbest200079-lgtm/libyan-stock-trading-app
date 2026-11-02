#pragma once
// النافذة الرئيسية لشاشة عرض أسهم سوق المال الليبي — كل اللوحات في شاشة واحدة
#include <QMainWindow>
#include "MarketData.h"

class QLabel;
class QTableWidget;
class QTimer;
class QGridLayout;
class QHBoxLayout;
class QFrame;

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
    struct Item { QString sym, price, pct; int dir; };
    QVector<Item> m_items;
    qreal m_offset = 0;
    QTimer *m_timer;
};

// ── رسم بياني مصغّر للمؤشر ──
class SparklineWidget : public QWidget {
    Q_OBJECT
public:
    explicit SparklineWidget(QWidget *parent = nullptr);
    void setSeries(const QVector<double> &s, int dir);
    QSize sizeHint() const override;
protected:
    void paintEvent(QPaintEvent *) override;
private:
    QVector<double> m_series;
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
    explicit DisplayWindow(QWidget *parent = nullptr);
protected:
    void keyPressEvent(QKeyEvent *e) override;
private slots:
    void tickClock();
    void reloadData();
private:
    void buildUi();
    void renderAll();
    void renderIndex();
    void renderStats();
    void renderTable();
    void renderMovers();
    void renderBottom();
    void setHall(bool on);
    QString dataPath() const;

    MarketData m_data;

    TickerWidget   *m_ticker = nullptr;
    QLabel         *m_sessDate = nullptr, *m_clock = nullptr, *m_status = nullptr, *m_note = nullptr;
    QLabel         *m_idxVal = nullptr, *m_idxChg = nullptr, *m_idxSub = nullptr;
    SparklineWidget*m_spark = nullptr;
    QLabel         *m_stVal = nullptr, *m_stVol = nullptr, *m_stTr = nullptr, *m_stN = nullptr, *m_stBreadthLbl = nullptr;
    BreadthBar     *m_breadth = nullptr;
    QTableWidget   *m_table = nullptr;
    QFrame         *m_upCard = nullptr, *m_dnCard = nullptr, *m_acCard = nullptr;
    QHBoxLayout    *m_heatRow = nullptr;     // صف خريطة السوق أسفل الشاشة
    QHBoxLayout    *m_sectorsRow = nullptr;  // سطر القطاعات

    QTimer *m_clockTimer = nullptr, *m_reloadTimer = nullptr;
    bool m_hall = false;
};
