#include "DisplayWindow.h"

#include <QApplication>
#include <QBoxLayout>
#include <QDateTime>
#include <QFileInfo>
#include <QFrame>
#include <QGridLayout>
#include <QHeaderView>
#include <QKeyEvent>
#include <QLabel>
#include <QLocale>
#include <QMap>
#include <QPainter>
#include <QPainterPath>
#include <QTableWidget>
#include <QTimer>
#include <algorithm>
#include <cmath>

// ───────────────────────── الألوان (Midnight Executive) ─────────────────────────
namespace clr {
const QColor BG("#0C1224"), SURFACE("#151E3B"), SURFACE2("#1E2761"), LINE("#2A3660");
const QColor FG("#E9EBF4"), MUTED("#8C94B2"), GOLD("#C9A961");
const QColor UP("#2EBD6B"), DOWN("#E5565C");
}

static QString fm(double v, int dec = 3)
{
    return QLocale(QLocale::English).toString(v, 'f', dec); // أرقام غربية مع فواصل الآلاف
}
static QString fmInt(double v) { return QLocale(QLocale::English).toString(qRound64(v)); }
static QColor dirColor(int d) { return d > 0 ? clr::UP : (d < 0 ? clr::DOWN : clr::MUTED); }
static QString arrSym(int d)  { return d > 0 ? QStringLiteral("▲") : (d < 0 ? QStringLiteral("▼") : QStringLiteral("•")); }

static void clearLayout(QLayout *lay)
{
    if (!lay) return;
    while (QLayoutItem *it = lay->takeAt(0)) {
        if (QWidget *w = it->widget()) w->deleteLater();
        if (QLayout *l = it->layout()) clearLayout(l);
        delete it;
    }
}

// ───────────────────────── الشريط المتحرك ─────────────────────────
TickerWidget::TickerWidget(QWidget *parent) : QWidget(parent)
{
    setAutoFillBackground(false);
    m_timer = new QTimer(this);
    m_timer->setInterval(30);
    connect(m_timer, &QTimer::timeout, this, [this] {
        m_offset += 1.2;
        update();
    });
    m_timer->start();
}
QSize TickerWidget::sizeHint() const { return QSize(600, 36); }
void TickerWidget::setData(const QVector<Stock> &stocks)
{
    m_items.clear();
    for (const Stock &s : stocks) {
        Item it;
        it.sym = s.sym;
        it.price = fm(s.last);
        it.pct = arrSym(s.dir()) + QStringLiteral(" ") + fm(std::abs(s.pct()), 2) + QStringLiteral("%");
        it.dir = s.dir();
        m_items.append(it);
    }
    update();
}
void TickerWidget::paintEvent(QPaintEvent *)
{
    QPainter p(this);
    p.fillRect(rect(), clr::SURFACE);
    p.setPen(QPen(clr::LINE, 1));
    p.drawLine(0, height() - 1, width(), height() - 1);
    if (m_items.isEmpty()) return;

    QFont fSym = font();  fSym.setBold(true);
    const QFontMetricsF fmx(fSym);
    const qreal pad = 18, gap = 10;

    qreal cycle = 0;
    QVector<qreal> widths;
    widths.reserve(m_items.size());
    for (const Item &it : m_items) {
        const qreal w = fmx.horizontalAdvance(it.sym) + gap
                      + fmx.horizontalAdvance(it.price) + gap
                      + fmx.horizontalAdvance(it.pct) + 2 * pad;
        widths.append(w);
        cycle += w;
    }
    if (cycle <= 0) return;
    const qreal off = std::fmod(m_offset, cycle);
    const qreal y = height() / 2.0 + fmx.ascent() / 2.0 - 2;

    qreal x = -off;
    while (x < width()) {
        for (int i = 0; i < m_items.size() && x < width(); ++i) {
            const Item &it = m_items[i];
            const qreal w = widths[i];
            if (x + w > 0) {
                qreal cx = x + pad;
                p.setFont(fSym);
                p.setPen(clr::FG);
                p.drawText(QPointF(cx, y), it.sym);
                cx += fmx.horizontalAdvance(it.sym) + gap;
                p.setPen(dirColor(it.dir));
                p.drawText(QPointF(cx, y), it.price);
                cx += fmx.horizontalAdvance(it.price) + gap;
                p.drawText(QPointF(cx, y), it.pct);
                p.setPen(QPen(clr::LINE, 1));
                p.drawLine(QPointF(x + w, 6), QPointF(x + w, height() - 7));
            }
            x += w;
        }
    }
}

// ───────────────────────── الرسم المصغّر ─────────────────────────
SparklineWidget::SparklineWidget(QWidget *parent) : QWidget(parent) {}
QSize SparklineWidget::sizeHint() const { return QSize(240, 46); }
void SparklineWidget::setSeries(const QVector<double> &s, int dir)
{
    m_series = s; m_dir = dir; update();
}
void SparklineWidget::paintEvent(QPaintEvent *)
{
    if (m_series.size() < 2) return;
    QPainter p(this);
    p.setRenderHint(QPainter::Antialiasing);
    const qreal pad = 3, W = width(), H = height();
    const double mn = *std::min_element(m_series.begin(), m_series.end());
    const double mx = *std::max_element(m_series.begin(), m_series.end());
    const double rng = (mx - mn) > 0 ? (mx - mn) : 1.0;

    QPainterPath line;
    QPointF last;
    for (int i = 0; i < m_series.size(); ++i) {
        const qreal x = pad + i * (W - 2 * pad) / (m_series.size() - 1);
        const qreal y = H - pad - (m_series[i] - mn) / rng * (H - 2 * pad);
        last = QPointF(x, y);
        if (i == 0) line.moveTo(last); else line.lineTo(last);
    }
    QPainterPath area = line;
    area.lineTo(W - pad, H); area.lineTo(pad, H); area.closeSubpath();

    QColor c = dirColor(m_dir);
    QColor fill = c; fill.setAlpha(34);
    p.fillPath(area, fill);
    p.setPen(QPen(c, 2));
    p.drawPath(line);
    p.setBrush(clr::GOLD);
    p.setPen(Qt::NoPen);
    p.drawEllipse(last, 3.5, 3.5);
}

// ───────────────────────── شريط الاتساع ─────────────────────────
BreadthBar::BreadthBar(QWidget *parent) : QWidget(parent) {}
QSize BreadthBar::sizeHint() const { return QSize(160, 8); }
void BreadthBar::setCounts(int up, int flat, int down)
{
    m_up = up; m_flat = flat; m_down = down; update();
}
void BreadthBar::paintEvent(QPaintEvent *)
{
    QPainter p(this);
    p.setRenderHint(QPainter::Antialiasing);
    const int total = m_up + m_flat + m_down;
    QPainterPath clip;
    clip.addRoundedRect(rect(), height() / 2.0, height() / 2.0);
    p.setClipPath(clip);
    p.fillRect(rect(), clr::SURFACE2);
    if (total <= 0) return;
    qreal x = 0;
    const qreal w = width();
    auto seg = [&](int n, const QColor &c) {
        const qreal sw = w * n / total;
        p.fillRect(QRectF(x, 0, sw, height()), c);
        x += sw;
    };
    seg(m_up, clr::UP); seg(m_flat, clr::MUTED); seg(m_down, clr::DOWN);
}

// ───────────────────────── النافذة الرئيسية ─────────────────────────
DisplayWindow::DisplayWindow(QWidget *parent) : QMainWindow(parent)
{
    setWindowTitle(QStringLiteral("شاشة أسهم سوق المال الليبي"));
    setLayoutDirection(Qt::RightToLeft);
    resize(1366, 820);

    QString err;
    if (!m_data.load(dataPath(), &err))
        m_data.loadDefaults();

    buildUi();
    renderAll();

    m_clockTimer = new QTimer(this);
    connect(m_clockTimer, &QTimer::timeout, this, &DisplayWindow::tickClock);
    m_clockTimer->start(1000);
    tickClock();

    m_reloadTimer = new QTimer(this);          // يلتقط تحديثات منظومة التغذية
    connect(m_reloadTimer, &QTimer::timeout, this, &DisplayWindow::reloadData);
    m_reloadTimer->start(15000);
}

QString DisplayWindow::dataPath() const
{
    return QCoreApplication::applicationDirPath() + QStringLiteral("/data/session.json");
}

static QLabel *lbl(const QString &t, const QString &style, QWidget *parent = nullptr)
{
    auto *l = new QLabel(t, parent);
    l->setStyleSheet(style);
    return l;
}

static QFrame *card()
{
    auto *f = new QFrame;
    f->setStyleSheet(QStringLiteral(
        "QFrame{background:%1;border:1px solid %2;border-radius:12px}")
        .arg(clr::SURFACE.name(), clr::LINE.name()));
    return f;
}

void DisplayWindow::buildUi()
{
    auto *central = new QWidget;
    central->setStyleSheet(QStringLiteral("background:%1;color:%2;")
                               .arg(clr::BG.name(), clr::FG.name()));
    auto *root = new QVBoxLayout(central);
    root->setContentsMargins(16, 10, 16, 10);
    root->setSpacing(10);

    // ── الشريط العلوي ──
    auto *top = new QHBoxLayout;
    auto *title = lbl(QStringLiteral("سوق المال الليبي — شاشة عرض الأسهم"),
                      QStringLiteral("font-size:16pt;font-weight:bold;"));
    m_sessDate = lbl(QString(), QStringLiteral("color:%1;font-size:10pt;").arg(clr::MUTED.name()));
    auto *tbox = new QVBoxLayout;
    tbox->setSpacing(0);
    tbox->addWidget(title);
    tbox->addWidget(m_sessDate);
    top->addLayout(tbox);
    top->addStretch(1);
    m_clock = lbl(QStringLiteral("--:--:--"),
                  QStringLiteral("font-size:14pt;font-weight:bold;letter-spacing:1px;"));
    m_status = lbl(QString(), QStringLiteral("font-size:10.5pt;font-weight:bold;padding:4px 14px;"
                                             "border:1px solid %1;border-radius:13px;").arg(clr::LINE.name()));
    top->addWidget(m_clock);
    top->addWidget(m_status);
    root->addLayout(top);

    // ── الشريط المتحرك ──
    m_ticker = new TickerWidget;
    m_ticker->setFixedHeight(36);
    QFont tf = m_ticker->font(); tf.setPointSizeF(11.5); m_ticker->setFont(tf);
    root->addWidget(m_ticker);

    // ── صف المؤشر + الإحصاءات ──
    auto *hero = new QHBoxLayout;
    hero->setSpacing(10);

    QFrame *idx = card();
    idx->setStyleSheet(idx->styleSheet() + QStringLiteral(
        "QFrame{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 %1,stop:1 %2);"
        "border-right:3px solid %3;}").arg(clr::SURFACE2.name(), clr::SURFACE.name(), clr::GOLD.name()));
    auto *il = new QHBoxLayout(idx);
    il->setContentsMargins(16, 8, 16, 8);
    il->setSpacing(16);
    auto *ivBox = new QVBoxLayout;
    ivBox->setSpacing(0);
    ivBox->addWidget(lbl(QStringLiteral("المؤشر العام"),
                         QStringLiteral("color:%1;font-size:9.5pt;border:none;background:transparent;").arg(clr::MUTED.name())));
    auto *ivRow = new QHBoxLayout;
    m_idxVal = lbl(QStringLiteral("—"), QStringLiteral("font-size:24pt;font-weight:bold;border:none;background:transparent;"));
    m_idxChg = lbl(QString(), QStringLiteral("font-size:12pt;font-weight:bold;border:none;background:transparent;"));
    ivRow->addWidget(m_idxVal);
    ivRow->addWidget(m_idxChg);
    ivRow->addStretch(1);
    ivBox->addLayout(ivRow);
    m_idxSub = lbl(QString(), QStringLiteral("color:%1;font-size:9pt;border:none;background:transparent;").arg(clr::MUTED.name()));
    ivBox->addWidget(m_idxSub);
    il->addLayout(ivBox, 0);
    m_spark = new SparklineWidget;
    m_spark->setMinimumSize(170, 46);
    il->addWidget(m_spark, 1);
    hero->addWidget(idx, 2);

    QFrame *stats = card();
    auto *sg = new QGridLayout(stats);
    sg->setContentsMargins(16, 8, 16, 8);
    sg->setHorizontalSpacing(24);
    sg->setVerticalSpacing(2);
    const QString slab = QStringLiteral("color:%1;font-size:9pt;border:none;background:transparent;").arg(clr::MUTED.name());
    const QString sval = QStringLiteral("font-size:13pt;font-weight:bold;border:none;background:transparent;");
    sg->addWidget(lbl(QStringLiteral("قيمة التداول (د.ل)"), slab), 0, 0);
    sg->addWidget(m_stVal = lbl(QStringLiteral("—"), sval), 1, 0);
    sg->addWidget(lbl(QStringLiteral("الكمية (سهم)"), slab), 0, 1);
    sg->addWidget(m_stVol = lbl(QStringLiteral("—"), sval), 1, 1);
    sg->addWidget(lbl(QStringLiteral("عدد الصفقات"), slab), 0, 2);
    sg->addWidget(m_stTr = lbl(QStringLiteral("—"), sval), 1, 2);
    sg->addWidget(lbl(QStringLiteral("الشركات المتداولة"), slab), 0, 3);
    sg->addWidget(m_stN = lbl(QStringLiteral("—"), sval), 1, 3);
    m_breadth = new BreadthBar;
    m_breadth->setFixedHeight(7);
    sg->addWidget(m_breadth, 2, 0, 1, 3);
    m_stBreadthLbl = lbl(QString(), slab);
    sg->addWidget(m_stBreadthLbl, 2, 3);
    hero->addWidget(stats, 3);
    root->addLayout(hero);

    // ── الصف الرئيسي: الجدول + عمود الأكثر تداولاً ──
    auto *mainRow = new QHBoxLayout;
    mainRow->setSpacing(10);

    m_table = new QTableWidget;
    m_table->setColumnCount(12);
    m_table->setHorizontalHeaderLabels({
        QStringLiteral("الرمز"), QStringLiteral("الشركة"), QStringLiteral("إغلاق سابق"),
        QStringLiteral("الافتتاح"), QStringLiteral("الأعلى"), QStringLiteral("الأدنى"),
        QStringLiteral("آخر سعر"), QStringLiteral("التغير"), QStringLiteral("التغير %"),
        QStringLiteral("الكمية"), QStringLiteral("القيمة (د.ل)"), QStringLiteral("الصفقات")});
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionMode(QAbstractItemView::NoSelection);
    m_table->setFocusPolicy(Qt::NoFocus);
    m_table->setShowGrid(false);
    m_table->setAlternatingRowColors(true);
    m_table->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    m_table->horizontalHeader()->setSectionResizeMode(1, QHeaderView::ResizeToContents);
    m_table->setSortingEnabled(false);
    m_table->setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);
    m_table->setStyleSheet(QStringLiteral(
        "QTableWidget{background:%1;alternate-background-color:%2;border:1px solid %3;border-radius:12px;font-size:10.5pt;}"
        "QTableWidget::item{padding:4px 8px;border:none;}"
        "QHeaderView::section{background:%4;color:%5;font-weight:bold;font-size:9pt;border:none;"
        "border-bottom:1px solid %3;padding:7px 8px;}")
        .arg(clr::SURFACE.name(), QStringLiteral("#182142"), clr::LINE.name(),
             clr::SURFACE2.name(), clr::MUTED.name()));
    mainRow->addWidget(m_table, 7);

    auto *side = new QVBoxLayout;
    side->setSpacing(10);
    side->addWidget(m_upCard = card(), 1);
    side->addWidget(m_dnCard = card(), 1);
    side->addWidget(m_acCard = card(), 1);
    new QVBoxLayout(m_upCard);
    new QVBoxLayout(m_dnCard);
    new QVBoxLayout(m_acCard);
    mainRow->addLayout(side, 3);

    root->addLayout(mainRow, 1);

    // ── أسفل الشاشة: خريطة السوق + القطاعات ──
    QFrame *bottom = card();
    auto *bl = new QVBoxLayout(bottom);
    bl->setContentsMargins(12, 8, 12, 8);
    bl->setSpacing(6);
    m_heatRow = new QHBoxLayout;
    m_heatRow->setSpacing(6);
    bl->addLayout(m_heatRow);
    m_sectorsRow = new QHBoxLayout;
    m_sectorsRow->setSpacing(24);
    bl->addLayout(m_sectorsRow);
    root->addWidget(bottom);

    // ── سطر الملاحظة ──
    m_note = lbl(QString(), QStringLiteral("color:%1;font-size:8.5pt;").arg(clr::MUTED.name()));
    root->addWidget(m_note);

    setCentralWidget(central);
}

void DisplayWindow::tickClock()
{
    const QDateTime now = QDateTime::currentDateTime();
    m_clock->setText(now.toString(QStringLiteral("HH:mm:ss")));

    bool open = false;
    const QString st = m_data.session.status;
    if (st == QLatin1String("open")) open = true;
    else if (st == QLatin1String("closed")) open = false;
    else {
        const int dow = now.date().dayOfWeek();          // الاثنين=1 … الأحد=7
        const bool tradingDay = (dow == 7 || dow <= 4);  // الأحد–الخميس
        const QTime t = now.time();
        const QTime o = QTime::fromString(m_data.session.openT, QStringLiteral("HH:mm"));
        const QTime c = QTime::fromString(m_data.session.closeT, QStringLiteral("HH:mm"));
        open = tradingDay && o.isValid() && c.isValid() && t >= o && t < c;
    }
    m_status->setText(open ? QStringLiteral("● جلسة التداول جارية") : QStringLiteral("● السوق مغلق"));
    m_status->setStyleSheet(QStringLiteral(
        "font-size:10.5pt;font-weight:bold;padding:4px 14px;border-radius:13px;"
        "border:1px solid %1;color:%1;background:%2;")
        .arg(open ? clr::UP.name() : clr::MUTED.name(), clr::SURFACE.name()));
}

void DisplayWindow::reloadData()
{
    if (!QFileInfo::exists(dataPath())) return;
    MarketData fresh = m_data;
    QString err;
    if (fresh.load(dataPath(), &err)) {
        m_data = fresh;
        renderAll();
    }
}

void DisplayWindow::keyPressEvent(QKeyEvent *e)
{
    switch (e->key()) {
    case Qt::Key_F11: setHall(!m_hall); return;
    case Qt::Key_Escape: if (m_hall) { setHall(false); return; } break;
    case Qt::Key_R: reloadData(); return;
    default: break;
    }
    QMainWindow::keyPressEvent(e);
}

void DisplayWindow::setHall(bool on)
{
    m_hall = on;
    if (on) showFullScreen(); else showNormal();
    renderAll();
}

void DisplayWindow::renderAll()
{
    m_sessDate->setText(QStringLiteral("جلسة ") + m_data.session.date
                        + (m_hall ? QString() : QStringLiteral("   —   F11 ملء الشاشة · R لإعادة التحميل")));
    m_note->setText(m_data.demo
        ? QStringLiteral("بيانات استرشادية للعرض — تُحدَّث من ملف data/session.json أو آليًا عبر منظومة التغذية من نظام التداول.")
        : QStringLiteral("المصدر: ملف data/session.json — يُحدَّث آليًا كل 15 ثانية."));
    m_ticker->setData(m_data.stocks);
    renderIndex();
    renderStats();
    renderTable();
    renderMovers();
    renderBottom();
}

void DisplayWindow::renderIndex()
{
    const IndexInfo &ix = m_data.index;
    m_idxVal->setText(fm(ix.value, 2));
    const int d = ix.dir();
    m_idxChg->setText(QStringLiteral("%1 %2 (%3%)")
                          .arg(arrSym(d), fm(std::abs(ix.chg()), 2), fm(std::abs(ix.pct()), 2)));
    m_idxChg->setStyleSheet(QStringLiteral("font-size:12pt;font-weight:bold;border:none;background:transparent;color:%1;")
                                .arg(dirColor(d).name()));
    QVector<double> ser = ix.series;
    if (ser.size() < 2) { ser.clear(); ser << ix.prev << ix.value; }
    const double hi = *std::max_element(ser.begin(), ser.end());
    const double lo = *std::min_element(ser.begin(), ser.end());
    m_idxSub->setText(QStringLiteral("سابق %1   أعلى %2   أدنى %3")
                          .arg(fm(ix.prev, 2), fm(hi, 2), fm(lo, 2)));
    m_spark->setSeries(ser, d);
}

void DisplayWindow::renderStats()
{
    const Totals t = m_data.totals();
    m_stVal->setText(fmInt(t.val));
    m_stVol->setText(fmInt(double(t.vol)));
    m_stTr->setText(fmInt(t.trades));
    m_stN->setText(QString::number(t.n));
    m_breadth->setCounts(t.up, t.flat, t.down);
    m_stBreadthLbl->setText(QStringLiteral("▲ %1   • %2   ▼ %3")
                                .arg(t.up).arg(t.flat).arg(t.down));
}

void DisplayWindow::renderTable()
{
    QVector<Stock> rows = m_data.stocks;
    std::sort(rows.begin(), rows.end(), [](const Stock &a, const Stock &b) { return a.val > b.val; });

    m_table->setRowCount(rows.size());
    const Qt::Alignment numAl = Qt::AlignLeft | Qt::AlignVCenter; // الأرقام يسارًا في واجهة RTL
    for (int r = 0; r < rows.size(); ++r) {
        const Stock &s = rows[r];
        const QColor c = dirColor(s.dir());
        auto set = [&](int col, const QString &txt, const QColor &fg, Qt::Alignment al, bool bold = false) {
            auto *it = new QTableWidgetItem(txt);
            it->setForeground(fg);
            it->setTextAlignment(al);
            if (bold) { QFont f = it->font(); f.setBold(true); it->setFont(f); }
            m_table->setItem(r, col, it);
        };
        set(0,  s.sym,  clr::GOLD, Qt::AlignCenter, true);
        set(1,  s.name, clr::FG,   Qt::AlignRight | Qt::AlignVCenter);
        set(2,  fm(s.prev), clr::FG, numAl);
        set(3,  fm(s.open), clr::FG, numAl);
        set(4,  fm(s.high), clr::FG, numAl);
        set(5,  fm(s.low),  clr::FG, numAl);
        set(6,  fm(s.last), c, numAl, true);
        set(7,  (s.chg() > 0 ? QStringLiteral("+") : QString()) + fm(s.chg()), c, numAl, true);
        set(8,  arrSym(s.dir()) + QStringLiteral(" ") + fm(std::abs(s.pct()), 2) + QStringLiteral("%"), c, numAl, true);
        set(9,  fmInt(double(s.vol)), clr::FG, numAl);
        set(10, fmInt(s.val), clr::FG, numAl);
        set(11, fmInt(s.trades), clr::FG, numAl);
        m_table->setRowHeight(r, m_hall ? 38 : 30);
    }
}

static void fillMoverCard(QFrame *cardFrame, const QString &title, const QColor &accent,
                          const QVector<Stock> &list, bool byValue)
{
    auto *lay = qobject_cast<QVBoxLayout *>(cardFrame->layout());
    clearLayout(lay);
    lay->setContentsMargins(12, 8, 12, 8);
    lay->setSpacing(4);
    auto *h = new QLabel(title);
    h->setStyleSheet(QStringLiteral("font-size:10pt;font-weight:bold;color:%1;border:none;background:transparent;")
                         .arg(accent.name()));
    lay->addWidget(h);
    int rank = 1;
    for (const Stock &s : list) {
        auto *row = new QHBoxLayout;
        auto *name = new QLabel(QStringLiteral("%1. %2").arg(rank++).arg(s.name));
        name->setStyleSheet(QStringLiteral("font-size:9.5pt;border:none;background:transparent;"));
        auto *px = new QLabel(byValue
            ? QStringLiteral("%1 د.ل").arg(fmInt(s.val))
            : QStringLiteral("%1 %2%").arg(arrSym(s.dir()), fm(std::abs(s.pct()), 2)));
        px->setStyleSheet(QStringLiteral("font-size:9.5pt;font-weight:bold;border:none;background:transparent;color:%1;")
                              .arg(dirColor(s.dir()).name()));
        row->addWidget(name, 1);
        row->addWidget(px);
        lay->addLayout(row);
    }
    lay->addStretch(1);
}

void DisplayWindow::renderMovers()
{
    QVector<Stock> ups = m_data.stocks, dns = m_data.stocks, act = m_data.stocks;
    std::sort(ups.begin(), ups.end(), [](const Stock &a, const Stock &b) { return a.pct() > b.pct(); });
    std::sort(dns.begin(), dns.end(), [](const Stock &a, const Stock &b) { return a.pct() < b.pct(); });
    std::sort(act.begin(), act.end(), [](const Stock &a, const Stock &b) { return a.val > b.val; });
    const int N = 4;
    ups = ups.mid(0, N); dns = dns.mid(0, N); act = act.mid(0, N);
    fillMoverCard(m_upCard, QStringLiteral("▲ الأكثر ارتفاعًا"), clr::UP, ups, false);
    fillMoverCard(m_dnCard, QStringLiteral("▼ الأكثر انخفاضًا"), clr::DOWN, dns, false);
    fillMoverCard(m_acCard, QStringLiteral("◆ الأكثر نشاطًا بالقيمة"), clr::GOLD, act, true);
}

static QColor heatColor(double pct)
{
    const double lim = 5.0;
    const double t = std::clamp(pct, -lim, lim) / lim; // -1 … 1
    const QColor base = clr::SURFACE2;
    if (std::abs(t) < 0.02) return base;
    const QColor target = t > 0 ? clr::UP : clr::DOWN;
    const double a = 0.20 + std::abs(t) * 0.55;
    auto mix = [&](int b, int g) { return int(b + (g - b) * a); };
    return QColor(mix(base.red(), target.red()),
                  mix(base.green(), target.green()),
                  mix(base.blue(), target.blue()));
}

void DisplayWindow::renderBottom()
{
    // صف خريطة السوق: بلاطة لكل شركة بعرض يتناسب مع قيمة تداولها
    clearLayout(m_heatRow);
    QVector<Stock> rows = m_data.stocks;
    std::sort(rows.begin(), rows.end(), [](const Stock &a, const Stock &b) { return a.val > b.val; });
    double total = 0;
    for (const Stock &s : rows) total += s.val;
    for (const Stock &s : rows) {
        auto *tile = new QFrame;
        tile->setStyleSheet(QStringLiteral("QFrame{background:%1;border:none;border-radius:8px;}")
                                .arg(heatColor(s.pct()).name()));
        auto *tl = new QVBoxLayout(tile);
        tl->setContentsMargins(8, 4, 8, 4);
        tl->setSpacing(0);
        auto *a = new QLabel(s.sym);
        a->setStyleSheet(QStringLiteral("font-size:9pt;font-weight:bold;border:none;background:transparent;"));
        a->setAlignment(Qt::AlignCenter);
        auto *b = new QLabel(QStringLiteral("%1 %2%").arg(arrSym(s.dir()), fm(std::abs(s.pct()), 2)));
        b->setStyleSheet(QStringLiteral("font-size:8.5pt;font-weight:bold;border:none;background:transparent;"));
        b->setAlignment(Qt::AlignCenter);
        tl->addWidget(a);
        tl->addWidget(b);
        const int stretch = total > 0 ? std::max(1, int(std::lround(s.val / total * 100))) : 1;
        m_heatRow->addWidget(tile, stretch);
    }

    // سطر القطاعات
    clearLayout(m_sectorsRow);
    struct Agg { double wsum = 0, w = 0, val = 0; int n = 0; };
    QMap<QString, Agg> map;
    for (const Stock &s : m_data.stocks) {
        Agg &a = map[s.sector];
        const double w = s.val > 0 ? s.val : 1.0;
        a.wsum += s.pct() * w; a.w += w; a.val += s.val; ++a.n;
    }
    auto *cap = new QLabel(QStringLiteral("القطاعات:"));
    cap->setStyleSheet(QStringLiteral("font-size:9.5pt;color:%1;border:none;background:transparent;").arg(clr::MUTED.name()));
    m_sectorsRow->addWidget(cap);
    for (auto it = map.constBegin(); it != map.constEnd(); ++it) {
        const double p = it.value().w > 0 ? it.value().wsum / it.value().w : 0;
        const int d = p > 1e-4 ? 1 : (p < -1e-4 ? -1 : 0);
        auto *l = new QLabel(QStringLiteral("%1 (%2): %3 %4%  —  %5 د.ل")
                                 .arg(it.key()).arg(it.value().n)
                                 .arg(arrSym(d), fm(std::abs(p), 2), fmInt(it.value().val)));
        l->setStyleSheet(QStringLiteral("font-size:9.5pt;font-weight:bold;border:none;background:transparent;color:%1;")
                             .arg(dirColor(d).name()));
        m_sectorsRow->addWidget(l);
    }
    m_sectorsRow->addStretch(1);
}
