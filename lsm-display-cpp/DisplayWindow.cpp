#include "DisplayWindow.h"

#include <QApplication>
#include <QBoxLayout>
#include <QDateTime>
#include <QDir>
#include <QFileInfo>
#include <QFrame>
#include <QGridLayout>
#include <QHeaderView>
#include <QKeyEvent>
#include <QLabel>
#include <QLocale>
#include <QPainter>
#include <QPainterPath>
#include <QScrollBar>
#include <QTableWidget>
#include <QTextStream>
#include <QTimer>
#include <algorithm>
#include <cmath>

// ───────────────────────── الألوان (Midnight Executive) ─────────────────────────
namespace clr {
const QColor BG("#0C1224"), SURFACE("#151E3B"), SURFACE2("#1E2761"), LINE("#2A3660");
const QColor FG("#E9EBF4"), MUTED("#8C94B2"), GOLD("#C9A961");
const QColor UP("#2EBD6B"), DOWN("#E5565C"), WARN("#E0A43A");
}

static QString fm(double v, int dec = 3)
{
    return QLocale(QLocale::English).toString(v, 'f', dec); // أرقام غربية مع فواصل الآلاف
}
static QString fmInt(double v) { return QLocale(QLocale::English).toString(qRound64(v)); }
static QColor dirColor(int d) { return d > 0 ? clr::UP : (d < 0 ? clr::DOWN : clr::MUTED); }
static QString arrSym(int d)  { return d > 0 ? QStringLiteral("▲") : (d < 0 ? QStringLiteral("▼") : QStringLiteral("•")); }

// عزل نص يساري الاتجاه (أرقام، إشارات، نسب) داخل واجهة عربية حتى لا تنقلب الإشارة أو موضع %
static QString ltr(const QString &s) { return QChar(0x2066) + s + QChar(0x2069); }
// "▼ 6.19%" بترتيب ثابت
static QString pctTxt(double pct, int d) { return ltr(arrSym(d) + QStringLiteral(" ") + fm(std::abs(pct), 2) + QStringLiteral("%")); }
static QString signedTxt(double v, int dec = 3)
{
    return ltr((v > 1e-9 ? QStringLiteral("+") : QString()) + fm(v, dec));
}
static const QString DASH = QStringLiteral("—");

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
    setLayoutDirection(Qt::LeftToRight);   // رسم يدوي — الاتجاه ثابت مهما كان اتجاه الواجهة
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
        it.traded = s.traded();
        m_items.append(it);
    }
    update();
}
void TickerWidget::paintEvent(QPaintEvent *)
{
    QPainter p(this);
    p.setLayoutDirection(Qt::LeftToRight);
    p.fillRect(rect(), clr::SURFACE);
    p.setPen(QPen(clr::LINE, 1));
    p.drawLine(0, height() - 1, width(), height() - 1);
    if (m_items.isEmpty()) return;

    QFont fSym = font();  fSym.setBold(true);
    p.setFont(fSym);
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
    if (m_offset > cycle * 1000) m_offset = std::fmod(m_offset, cycle);  // تجنّب تضخم العدّاد في التشغيل الدائم
    const qreal off = std::fmod(m_offset, cycle);
    const qreal y = height() / 2.0 + fmx.ascent() / 2.0 - 2;

    qreal x = -off;
    while (x < width()) {
        for (int i = 0; i < m_items.size() && x < width(); ++i) {
            const Item &it = m_items[i];
            const qreal w = widths[i];
            if (x + w > 0) {
                qreal cx = x + pad;
                p.setPen(it.traded ? clr::GOLD : clr::MUTED);
                p.drawText(QPointF(cx, y), it.sym);
                cx += fmx.horizontalAdvance(it.sym) + gap;
                p.setPen(it.traded ? (it.dir ? dirColor(it.dir) : clr::FG) : clr::MUTED);
                p.drawText(QPointF(cx, y), it.price);
                cx += fmx.horizontalAdvance(it.price) + gap;
                p.setPen(dirColor(it.dir));
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
void SparklineWidget::setSeries(const QVector<double> &s, double baseline, int dir)
{
    m_series = s; m_base = baseline; m_dir = dir; update();
}
void SparklineWidget::paintEvent(QPaintEvent *)
{
    if (m_series.size() < 2) return;
    QPainter p(this);
    p.setRenderHint(QPainter::Antialiasing);
    const qreal pad = 4, W = width(), H = height();
    double mn = *std::min_element(m_series.begin(), m_series.end());
    double mx = *std::max_element(m_series.begin(), m_series.end());
    if (m_base > 0) { mn = std::min(mn, m_base); mx = std::max(mx, m_base); }
    double rng = mx - mn;
    if (rng <= 0) { rng = std::max(1.0, std::abs(mx) * 0.01); mn -= rng / 2; }   // سلسلة ثابتة ← خط في المنتصف
    auto yOf = [&](double v) { return H - pad - (v - mn) / rng * (H - 2 * pad); };

    // خط الإغلاق السابق (مرجع)
    if (m_base > 0) {
        QPen dash(clr::MUTED, 1, Qt::DashLine);
        p.setPen(dash);
        p.drawLine(QPointF(pad, yOf(m_base)), QPointF(W - pad, yOf(m_base)));
    }

    QPainterPath line;
    QPointF last;
    for (int i = 0; i < m_series.size(); ++i) {
        const qreal x = pad + i * (W - 2 * pad) / (m_series.size() - 1);
        last = QPointF(x, yOf(m_series[i]));
        if (i == 0) line.moveTo(last); else line.lineTo(last);
    }
    QPainterPath area = line;
    area.lineTo(W - pad, H); area.lineTo(pad, H); area.closeSubpath();

    const QColor c = dirColor(m_dir);
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
    const bool rtl = layoutDirection() == Qt::RightToLeft;   // الصاعد يبدأ من جهة القراءة
    const qreal w = width();
    qreal x = 0;
    auto seg = [&](int n, const QColor &c) {
        const qreal sw = w * n / total;
        const qreal left = rtl ? w - x - sw : x;
        p.fillRect(QRectF(left, 0, sw, height()), c);
        x += sw;
    };
    seg(m_up, clr::UP); seg(m_flat, clr::MUTED); seg(m_down, clr::DOWN);
}

// ───────────────────────── النافذة الرئيسية ─────────────────────────
DisplayWindow::DisplayWindow(const DisplayOptions &opt, QWidget *parent)
    : QMainWindow(parent), m_opt(opt)
{
    if (m_opt.dataPath.isEmpty())
        m_opt.dataPath = QCoreApplication::applicationDirPath() + QStringLiteral("/data/session.json");

    setWindowTitle(QStringLiteral("شاشة أسهم سوق المال الليبي"));
    setLayoutDirection(Qt::RightToLeft);
    resize(1366, 820);

    if (!m_data.load(m_opt.dataPath, &m_loadError))
        m_data.loadDefaults();
    else {
        const QFileInfo fi(m_opt.dataPath);
        m_sig = filesSig();
    }
    m_warnings = m_data.validate();

    buildUi();
    renderAll();

    m_clockTimer = new QTimer(this);
    connect(m_clockTimer, &QTimer::timeout, this, &DisplayWindow::tickClock);
    m_clockTimer->start(1000);
    tickClock();

    // يفحص تعديل الملف دوريًا ويعيد القراءة فقط عند تغيّره (يلتقط تحديثات منظومة التغذية)
    m_reloadTimer = new QTimer(this);
    connect(m_reloadTimer, &QTimer::timeout, this, [this] { reloadData(false); });
    m_reloadTimer->start(std::max(1000, m_opt.pollMs));

    m_pageTimer = new QTimer(this);
    connect(m_pageTimer, &QTimer::timeout, this, &DisplayWindow::pageTable);
    m_pageTimer->start(std::max(3, m_opt.pageSeconds) * 1000);
}

void DisplayWindow::start()
{
    if (m_opt.fullscreen) setHall(true); else show();

    if (!m_opt.snapshotPath.isEmpty()) {
        QTimer::singleShot(1500, this, [this] {
            const bool ok = grab().save(m_opt.snapshotPath);
            QTextStream(stderr) << (ok ? "snapshot saved: " : "snapshot FAILED: ") << m_opt.snapshotPath << "\n";
            QCoreApplication::exit(ok ? 0 : 2);
        });
    }
}

static QLabel *lbl(const QString &t, const QString &style, QWidget *parent = nullptr)
{
    auto *l = new QLabel(t, parent);
    l->setStyleSheet(style);
    return l;
}

// بطاقة: المحدِّد باسم الكائن حتى لا يرث QLabel (وهو QFrame) الإطار والخلفية
static QFrame *card(const char *name = "card")
{
    auto *f = new QFrame;
    f->setObjectName(QString::fromLatin1(name));
    f->setStyleSheet(QStringLiteral(
        "QFrame#%3{background:%1;border:1px solid %2;border-radius:12px}")
        .arg(clr::SURFACE.name(), clr::LINE.name(), QString::fromLatin1(name)));
    return f;
}

static const QString kPlain = QStringLiteral("border:none;background:transparent;");

void DisplayWindow::buildUi()
{
    auto *central = new QWidget;
    central->setObjectName(QStringLiteral("central"));
    central->setStyleSheet(QStringLiteral("QWidget#central{background:%1;} QLabel{color:%2;}")
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
    m_status = lbl(QString(), QString());
    top->addWidget(m_clock, 0, Qt::AlignVCenter);
    top->addSpacing(8);
    top->addWidget(m_status, 0, Qt::AlignVCenter);
    root->addLayout(top);

    // ── الشريط المتحرك ──
    m_ticker = new TickerWidget;
    m_ticker->setFixedHeight(36);
    QFont tf = m_ticker->font(); tf.setPointSizeF(11.5); m_ticker->setFont(tf);
    root->addWidget(m_ticker);

    // ── صف المؤشر + الإحصاءات ──
    auto *hero = new QHBoxLayout;
    hero->setSpacing(10);

    QFrame *idx = card("idxCard");
    idx->setStyleSheet(QStringLiteral(
        "QFrame#idxCard{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 %1,stop:1 %2);"
        "border:1px solid %4;border-radius:12px;border-right:3px solid %3;}")
        .arg(clr::SURFACE2.name(), clr::SURFACE.name(), clr::GOLD.name(), clr::LINE.name()));
    auto *il = new QHBoxLayout(idx);
    il->setContentsMargins(16, 8, 16, 8);
    il->setSpacing(16);
    auto *ivBox = new QVBoxLayout;
    ivBox->setSpacing(0);
    ivBox->addWidget(lbl(QStringLiteral("المؤشر العام"),
                         QStringLiteral("color:%1;font-size:9.5pt;").arg(clr::MUTED.name()) + kPlain));
    auto *ivRow = new QHBoxLayout;
    m_idxVal = lbl(DASH, QStringLiteral("font-size:24pt;font-weight:bold;") + kPlain);
    m_idxChg = lbl(QString(), QStringLiteral("font-size:12pt;font-weight:bold;") + kPlain);
    ivRow->addWidget(m_idxVal);
    ivRow->addSpacing(6);
    ivRow->addWidget(m_idxChg);
    ivRow->addStretch(1);
    ivBox->addLayout(ivRow);
    m_idxSub = lbl(QString(), QStringLiteral("color:%1;font-size:9pt;").arg(clr::MUTED.name()) + kPlain);
    ivBox->addWidget(m_idxSub);
    il->addLayout(ivBox, 0);
    m_spark = new SparklineWidget;
    m_spark->setMinimumSize(170, 46);
    il->addWidget(m_spark, 1);
    hero->addWidget(idx, 4);

    QFrame *stats = card("statsCard");
    auto *sg = new QGridLayout(stats);
    sg->setContentsMargins(16, 8, 16, 8);
    sg->setHorizontalSpacing(24);
    sg->setVerticalSpacing(2);
    const QString slab = QStringLiteral("color:%1;font-size:9pt;").arg(clr::MUTED.name()) + kPlain;
    const QString sval = QStringLiteral("font-size:13pt;font-weight:bold;") + kPlain;
    sg->addWidget(lbl(QStringLiteral("قيمة التداول (د.ل)"), slab), 0, 0);
    sg->addWidget(m_stVal = lbl(DASH, sval), 1, 0);
    sg->addWidget(lbl(QStringLiteral("الكمية (سهم)"), slab), 0, 1);
    sg->addWidget(m_stVol = lbl(DASH, sval), 1, 1);
    sg->addWidget(lbl(QStringLiteral("عدد الصفقات"), slab), 0, 2);
    sg->addWidget(m_stTr = lbl(DASH, sval), 1, 2);
    sg->addWidget(lbl(QStringLiteral("الشركات المتداولة / المدرجة"), slab), 0, 3);
    sg->addWidget(m_stN = lbl(DASH, sval), 1, 3);
    sg->addWidget(lbl(QStringLiteral("القيمة السوقية (م.د.ل)"), slab), 0, 4);
    sg->addWidget(m_stCap = lbl(DASH, sval), 1, 4);
    m_stCapSub = lbl(QString(), QStringLiteral("font-size:9pt;") + kPlain);
    m_stCapSub->setTextFormat(Qt::RichText);
    sg->addWidget(m_stCapSub, 2, 4);
    m_breadth = new BreadthBar;
    m_breadth->setFixedHeight(7);
    sg->addWidget(m_breadth, 2, 0, 1, 2);
    m_stBreadthLbl = lbl(QString(), QStringLiteral("font-size:9pt;") + kPlain);
    m_stBreadthLbl->setTextFormat(Qt::RichText);
    sg->addWidget(m_stBreadthLbl, 2, 2, 1, 2);
    hero->addWidget(stats, 7);
    root->addLayout(hero);

    // ── الصف الرئيسي: الجدول + عمود الأكثر تداولاً ──
    auto *mainRow = new QHBoxLayout;
    mainRow->setSpacing(10);

    m_table = new QTableWidget;
    m_table->setColumnCount(13);
    m_table->setHorizontalHeaderLabels({
        QStringLiteral("الرمز"), QStringLiteral("الشركة"), QStringLiteral("إغلاق سابق"),
        QStringLiteral("الافتتاح"), QStringLiteral("الأعلى"), QStringLiteral("الأدنى"),
        QStringLiteral("آخر سعر"), QStringLiteral("التغير"), QStringLiteral("التغير %"),
        QStringLiteral("الكمية"), QStringLiteral("القيمة (د.ل)"), QStringLiteral("الصفقات"),
        QStringLiteral("ق.سوقية (م)")});
    m_table->verticalHeader()->setVisible(false);
    m_table->verticalHeader()->setMinimumSectionSize(20);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionMode(QAbstractItemView::NoSelection);
    m_table->setFocusPolicy(Qt::NoFocus);
    m_table->setShowGrid(false);
    m_table->setAlternatingRowColors(true);
    m_table->setWordWrap(false);
    m_table->setTextElideMode(Qt::ElideNone);
    m_table->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_table->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);   // يُمرَّر آليًا (لا يوجد مستخدم على شاشة العرض)
    QHeaderView *hh = m_table->horizontalHeader();
    hh->setSectionResizeMode(QHeaderView::Stretch);                 // الأعمدة الرقمية تتقاسم العرض
    hh->setSectionResizeMode(1, QHeaderView::ResizeToContents);     // اسم الشركة كاملًا دون اقتطاع
    hh->setMinimumSectionSize(40);
    hh->setDefaultAlignment(Qt::AlignCenter);
    m_table->setSortingEnabled(false);
    m_table->setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);
    m_table->setStyleSheet(QStringLiteral(
        "QTableWidget{background:%1;alternate-background-color:%2;border:1px solid %3;border-radius:12px;font-size:10.5pt;color:%6;}"
        "QTableWidget::item{padding:0px 3px;border:none;}"
        "QHeaderView::section{background:%4;color:%5;font-weight:bold;font-size:9pt;border:none;"
        "border-bottom:1px solid %3;padding:7px 2px;}")
        .arg(clr::SURFACE.name(), QStringLiteral("#182142"), clr::LINE.name(),
             clr::SURFACE2.name(), clr::MUTED.name(), clr::FG.name()));
    m_table->viewport()->installEventFilter(this);
    mainRow->addWidget(m_table, 1);

    auto *side = new QVBoxLayout;
    side->setSpacing(10);
    side->addWidget(m_upCard = card("upCard"), 1);
    side->addWidget(m_dnCard = card("dnCard"), 1);
    side->addWidget(m_acCard = card("acCard"), 1);
    new QVBoxLayout(m_upCard);
    new QVBoxLayout(m_dnCard);
    new QVBoxLayout(m_acCard);
    auto *sideW = new QWidget;
    sideW->setLayout(side);
    side->setContentsMargins(0, 0, 0, 0);
    sideW->setFixedWidth(330);                                      // عمود جانبي ثابت — باقي العرض للجدول
    mainRow->addWidget(sideW);

    root->addLayout(mainRow, 1);

    // ── أسفل الشاشة: خريطة السوق + القطاعات ──
    QFrame *bottom = card("bottomCard");
    auto *bl = new QVBoxLayout(bottom);
    bl->setContentsMargins(12, 8, 12, 8);
    bl->setSpacing(6);
    m_heatRow = new QHBoxLayout;
    m_heatRow->setSpacing(6);
    bl->addLayout(m_heatRow);
    m_sectorsRow = new QHBoxLayout;
    m_sectorsRow->setSpacing(28);
    bl->addLayout(m_sectorsRow);
    root->addWidget(bottom);

    // ── سطر الملاحظة ──
    m_note = lbl(QString(), QStringLiteral("color:%1;font-size:8.5pt;").arg(clr::MUTED.name()));
    m_note->setTextFormat(Qt::RichText);
    root->addWidget(m_note);

    setCentralWidget(central);
}

bool DisplayWindow::sessionOpenNow(const QDateTime &now) const
{
    const QString st = m_data.session.status;
    if (st == QLatin1String("open")) return true;
    if (st == QLatin1String("closed")) return false;
    const int dow = now.date().dayOfWeek();          // الاثنين=1 … الأحد=7
    const bool tradingDay = (dow == 7 || dow <= 4);  // الأحد–الخميس
    const QTime t = now.time();
    const QTime o = QTime::fromString(m_data.session.openT, QStringLiteral("H:mm"));
    const QTime c = QTime::fromString(m_data.session.closeT, QStringLiteral("H:mm"));
    return tradingDay && o.isValid() && c.isValid() && t >= o && t < c;
}

void DisplayWindow::tickClock()
{
    const QDateTime now = QDateTime::currentDateTime();
    m_clock->setText(ltr(now.toString(QStringLiteral("HH:mm:ss"))));

    const bool open = sessionOpenNow(now);
    // أثناء الجلسة: إن لم يتغير الملف منذ مدة طويلة فالأرقام المعروضة قد تكون قديمة
    const bool stale = open && !m_data.demo && m_data.fileModified.isValid()
                       && m_data.fileModified.secsTo(now) > m_opt.staleMinutes * 60;

    QString text; QColor c;
    if (!open)       { text = QStringLiteral("● السوق مغلق");                      c = clr::MUTED; }
    else if (stale)  { text = QStringLiteral("● الجلسة جارية — بانتظار التحديث");  c = clr::WARN; }
    else             { text = QStringLiteral("● جلسة التداول جارية");               c = clr::UP; }
    m_status->setText(text);
    m_status->setStyleSheet(QStringLiteral(
        "font-size:10.5pt;font-weight:bold;padding:4px 14px;border-radius:13px;"
        "border:1px solid %1;color:%1;background:%2;")
        .arg(c.name(), clr::SURFACE.name()));

    if (now.time().second() == 0) renderNote();   // تحديث «منذ x دقيقة» مرة في الدقيقة
}

QString DisplayWindow::filesSig() const
{
    QString sig;
    const QFileInfo d(m_opt.dataPath);
    for (const QFileInfo &fi : {d, QFileInfo(d.dir().filePath(QStringLiteral("companies.json")))})
        sig += fi.exists() ? fi.lastModified().toString(Qt::ISODateWithMs) + QLatin1Char('/') + QString::number(fi.size()) + QLatin1Char(';')
                           : QStringLiteral("-;");
    return sig;
}

void DisplayWindow::reloadData(bool force)
{
    const QFileInfo fi(m_opt.dataPath);
    if (!fi.exists()) {
        m_loadError = QStringLiteral("ملف البيانات غير موجود: ") + m_opt.dataPath;
        renderNote();
        return;
    }
    const QString sig = filesSig();
    if (!force && sig == m_sig && m_loadError.isEmpty())
        return;                                   // لم يتغير شيء — لا داعي لإعادة البناء

    MarketData fresh = m_data;
    QString err;
    if (fresh.load(m_opt.dataPath, &err)) {
        m_data = fresh;
        m_loadError.clear();
        m_sig = sig;
        m_warnings = m_data.validate();
        for (const QString &w : m_warnings)
            QTextStream(stderr) << "[تحذير بيانات] " << w << "\n";
        renderAll();
    } else {
        // تبقى آخر بيانات سليمة معروضة؛ قد يكون الملف في منتصف الكتابة فيُعاد المحاولة لاحقًا
        m_loadError = err;
        QTextStream(stderr) << "[خطأ قراءة] " << err << "\n";
        renderNote();
    }
}

void DisplayWindow::keyPressEvent(QKeyEvent *e)
{
    switch (e->key()) {
    case Qt::Key_F11: setHall(!m_hall); return;
    case Qt::Key_Escape: if (m_hall) { setHall(false); return; } break;
    case Qt::Key_R:
    case Qt::Key_F5: reloadData(true); return;
    default: break;
    }
    // مفتاح R على لوحة المفاتيح العربية يعطي «ق»
    if (e->text() == QStringLiteral("ق")) { reloadData(true); return; }
    QMainWindow::keyPressEvent(e);
}

void DisplayWindow::setHall(bool on)
{
    m_hall = on;
    if (on) { showFullScreen(); setCursor(Qt::BlankCursor); }
    else    { showNormal();     unsetCursor(); }
    renderAll();
}

// ارتفاع الصف يتكيّف ليعرض كل الشركات إن أمكن؛ وإلا يُستخدم الحد الأدنى ويتولى التمرير الآلي الباقي
void DisplayWindow::fitRows()
{
    const int n = m_table->rowCount();
    if (n == 0) return;
    const int avail = m_table->viewport()->height();
    const int minH = 26, maxH = m_hall ? 46 : 34;
    const int h = std::clamp(avail / n, minH, maxH);
    for (int r = 0; r < n; ++r) m_table->setRowHeight(r, h);
}

bool DisplayWindow::eventFilter(QObject *o, QEvent *e)
{
    if (m_table && o == m_table->viewport() && e->type() == QEvent::Resize)
        fitRows();
    return QMainWindow::eventFilter(o, e);
}

void DisplayWindow::pageTable()
{
    QScrollBar *sb = m_table->verticalScrollBar();
    if (sb->maximum() <= 0) return;
    const int next = sb->value() + m_table->viewport()->height() - m_table->rowHeight(0);
    sb->setValue(sb->value() >= sb->maximum() ? 0 : std::min(next, sb->maximum()));
}

void DisplayWindow::renderAll()
{
    renderHeader();
    m_ticker->setData(m_data.stocks);
    renderIndex();
    renderStats();
    renderTable();
    renderMovers();
    renderBottom();
    renderNote();
}

void DisplayWindow::renderHeader()
{
    QString dateTxt = m_data.session.date;
    const QDate d = QDate::fromString(m_data.session.date, Qt::ISODate);
    if (d.isValid())
        dateTxt = QLocale(QLocale::Arabic, QLocale::Libya).dayName(d.dayOfWeek()) + QStringLiteral(" ")
                  + ltr(d.toString(QStringLiteral("dd/MM/yyyy")));
    QString t = QStringLiteral("جلسة ") + dateTxt;
    if (!m_hall) t += QStringLiteral("   —   F11 ملء الشاشة · R لإعادة التحميل");
    m_sessDate->setText(t);
}

void DisplayWindow::renderNote()
{
    QStringList parts;
    const QString warnClr = clr::WARN.name();
    if (m_data.demo)
        parts << QStringLiteral("بيانات استرشادية للعرض — تُحدَّث من ملف data/session.json أو آليًا عبر منظومة التغذية.");
    else {
        QString src = QStringLiteral("المصدر: ملف بيانات الجلسة");
        if (m_data.fileModified.isValid())
            src += QStringLiteral(" — آخر تحديث ") + ltr(m_data.fileModified.toString(QStringLiteral("HH:mm")));
        parts << src;
    }
    const QDate sd = QDate::fromString(m_data.session.date, Qt::ISODate);
    if (sd.isValid() && sd != QDate::currentDate() && !m_data.demo)
        parts << QStringLiteral("<span style='color:%1'>الأرقام لجلسة سابقة</span>").arg(warnClr);
    if (!m_loadError.isEmpty())
        parts << QStringLiteral("<span style='color:%1'>تعذّر تحديث البيانات (تُعرض آخر نسخة سليمة): %2</span>")
                     .arg(clr::DOWN.name(), m_loadError.toHtmlEscaped());
    // تحذيرات سلامة البيانات تظهر للمشغّل فقط، لا للجمهور في وضع القاعة
    if (!m_warnings.isEmpty() && !m_hall) {
        QStringList shown = m_warnings.mid(0, 3);
        for (QString &s : shown) s = s.toHtmlEscaped();
        QString w = QStringLiteral("فحص البيانات (%1): ").arg(m_warnings.size()) + shown.join(QStringLiteral(" · "));
        if (m_warnings.size() > 3) w += QStringLiteral(" …");
        parts << QStringLiteral("<span style='color:%1'>%2</span>").arg(warnClr, w);
    }
    m_note->setText(parts.join(QStringLiteral("   |   ")));
}

void DisplayWindow::renderIndex()
{
    const IndexInfo &ix = m_data.index;
    m_idxVal->setText(ltr(fm(ix.value, 2)));
    const int d = ix.dir();
    m_idxChg->setText(ltr(QStringLiteral("%1 %2 (%3%)")
                          .arg(arrSym(d), fm(std::abs(ix.chg()), 2), fm(std::abs(ix.pct()), 2))));
    m_idxChg->setStyleSheet(QStringLiteral("font-size:12pt;font-weight:bold;color:%1;").arg(dirColor(d).name()) + kPlain);
    QVector<double> ser = ix.series;
    if (ser.size() < 2) { ser.clear(); ser << ix.prev << ix.value; }
    const double hi = *std::max_element(ser.begin(), ser.end());
    const double lo = *std::min_element(ser.begin(), ser.end());
    m_idxSub->setText(QStringLiteral("سابق %1   أعلى %2   أدنى %3")
                          .arg(ltr(fm(ix.prev, 2)), ltr(fm(hi, 2)), ltr(fm(lo, 2))));
    m_spark->setSeries(ser, ix.prev, d);
}

void DisplayWindow::renderStats()
{
    const Totals t = m_data.totals();
    m_stVal->setText(ltr(fmInt(t.val)));
    m_stVol->setText(ltr(fmInt(double(t.vol))));
    m_stTr->setText(ltr(fmInt(t.trades)));
    m_stN->setText(ltr(QStringLiteral("%1 / %2").arg(t.tradedN).arg(t.n)));
    // القيمة السوقية: تُعرض فقط إن عُرف عدد أسهم شركة واحدة على الأقل، مع بيان التغطية إن كانت جزئية
    if (t.mcapN > 0) {
        const int d = t.mcapPct() > 1e-4 ? 1 : (t.mcapPct() < -1e-4 ? -1 : 0);
        m_stCap->setText(ltr(fm(t.mcap / 1e6, 1)));
        QString sub = QStringLiteral("<span style='color:%1'>%2</span>").arg(dirColor(d).name(), pctTxt(t.mcapPct(), d));
        sub += QStringLiteral(" <span style='color:%1'>· دوران %2</span>")
                   .arg(clr::MUTED.name(), ltr(fm(t.turnoverPct(), 3) + QStringLiteral("%")));
        if (!t.mcapComplete())
            sub += QStringLiteral(" <span style='color:%1'>· %2 شركة</span>")
                       .arg(clr::WARN.name(), ltr(QStringLiteral("%1/%2").arg(t.mcapN).arg(t.n)));
        m_stCapSub->setText(sub);
    } else {
        m_stCap->setText(DASH);
        m_stCapSub->setText(QStringLiteral("<span style='color:%1'>بانتظار عدد الأسهم</span>").arg(clr::MUTED.name()));
    }
    m_breadth->setCounts(t.up, t.flat, t.down);
    m_stBreadthLbl->setText(QStringLiteral(
        "<span style='color:%1'>صاعد %2</span> &nbsp;·&nbsp; "
        "<span style='color:%3'>مستقر %4</span> &nbsp;·&nbsp; "
        "<span style='color:%5'>هابط %6</span>")
        .arg(clr::UP.name()).arg(t.up).arg(clr::MUTED.name()).arg(t.flat)
        .arg(clr::DOWN.name()).arg(t.down));
}

void DisplayWindow::renderTable()
{
    QVector<Stock> rows = m_data.stocks;
    MarketData::sortByValue(rows);

    const int keepScroll = m_table->verticalScrollBar()->value();
    m_table->setUpdatesEnabled(false);
    m_table->clearContents();
    m_table->setRowCount(rows.size());
    const Qt::Alignment numAl = Qt::AlignCenter;
    const Qt::Alignment nameAl = Qt::AlignLeading | Qt::AlignVCenter;  // يمين الخلية في الواجهة العربية
    for (int r = 0; r < rows.size(); ++r) {
        const Stock &s = rows[r];
        const bool tr = s.traded();
        const QColor c = dirColor(s.dir());
        const QColor base = tr ? clr::FG : clr::MUTED;
        auto set = [&](int col, const QString &txt, const QColor &fg, Qt::Alignment al, bool bold = false) {
            auto *it = new QTableWidgetItem(txt);
            it->setForeground(fg);
#if QT_VERSION >= QT_VERSION_CHECK(6, 4, 0)
            it->setTextAlignment(al);
#else
            it->setTextAlignment(int(al));
#endif
            if (bold) { QFont f = it->font(); f.setBold(true); it->setFont(f); }
            m_table->setItem(r, col, it);
        };
        auto px = [&](double v) { return (tr && v > 0) ? fm(v) : DASH; };
        set(0,  s.sym,  tr ? clr::GOLD : clr::MUTED, Qt::AlignCenter, true);
        set(1,  s.name, base, nameAl);
        set(2,  fm(s.prev), base, numAl);
        set(3,  px(s.open), base, numAl);
        set(4,  px(s.high), base, numAl);
        set(5,  px(s.low),  base, numAl);
        set(6,  fm(s.last), s.dir() ? c : base, numAl, true);
        set(7,  signedTxt(s.chg()), c, numAl, true);
        set(8,  pctTxt(s.pct(), s.dir()), c, numAl, true);
        set(9,  tr ? fmInt(double(s.vol)) : DASH, base, numAl);
        set(10, tr ? fmInt(s.val) : DASH, base, numAl);
        set(11, tr ? fmInt(s.trades) : DASH, base, numAl);
        set(12, s.hasMcap() ? fm(s.mcap() / 1e6, 1) : DASH, s.hasMcap() ? clr::FG : clr::MUTED, numAl);
    }
    fitRows();
    m_table->setUpdatesEnabled(true);
    m_table->verticalScrollBar()->setValue(keepScroll);
}

static void fillMoverCard(QFrame *cardFrame, const QString &title, const QColor &accent,
                          const QVector<Stock> &list, bool byValue)
{
    auto *lay = qobject_cast<QVBoxLayout *>(cardFrame->layout());
    clearLayout(lay);
    lay->setContentsMargins(12, 8, 12, 8);
    lay->setSpacing(4);
    lay->addWidget(lbl(title, QStringLiteral("font-size:10pt;font-weight:bold;color:%1;").arg(accent.name()) + kPlain));
    if (list.isEmpty()) {
        lay->addWidget(lbl(QStringLiteral("لا يوجد في هذه الجلسة"),
                           QStringLiteral("font-size:9.5pt;color:%1;").arg(clr::MUTED.name()) + kPlain));
    }
    int rank = 1;
    for (const Stock &s : list) {
        auto *row = new QHBoxLayout;
        auto *name = lbl(QStringLiteral("%1. %2").arg(rank++).arg(s.name), QStringLiteral("font-size:9.5pt;") + kPlain);
        QLabel *px;
        if (byValue)
            px = lbl(ltr(fmInt(s.val)) + QStringLiteral(" د.ل"),
                     QStringLiteral("font-size:9.5pt;font-weight:bold;color:%1;").arg(clr::FG.name()) + kPlain);
        else
            px = lbl(ltr(fm(s.last)) + QStringLiteral("  ") + pctTxt(s.pct(), s.dir()),
                     QStringLiteral("font-size:9.5pt;font-weight:bold;color:%1;").arg(dirColor(s.dir()).name()) + kPlain);
        row->addWidget(name, 1);
        row->addWidget(px);
        lay->addLayout(row);
    }
    lay->addStretch(1);
}

void DisplayWindow::renderMovers()
{
    // الأكثر ارتفاعًا/انخفاضًا: فقط الأسهم التي تغيّر سعرها فعلًا في الاتجاه المعني
    QVector<Stock> ups, dns, act;
    for (const Stock &s : m_data.stocks) {
        if (s.dir() > 0) ups << s;
        if (s.dir() < 0) dns << s;
        if (s.val > 0)   act << s;
    }
    std::stable_sort(ups.begin(), ups.end(), [](const Stock &a, const Stock &b) { return a.pct() > b.pct(); });
    std::stable_sort(dns.begin(), dns.end(), [](const Stock &a, const Stock &b) { return a.pct() < b.pct(); });
    MarketData::sortByValue(act);
    const int N = 4;
    ups = ups.mid(0, N); dns = dns.mid(0, N); act = act.mid(0, N);
    fillMoverCard(m_upCard, QStringLiteral("▲ الأكثر ارتفاعًا"), clr::UP, ups, false);
    fillMoverCard(m_dnCard, QStringLiteral("▼ الأكثر انخفاضًا"), clr::DOWN, dns, false);
    fillMoverCard(m_acCard, QStringLiteral("◆ الأكثر نشاطًا بالقيمة"), clr::GOLD, act, true);
}

static QColor heatColor(double pct, bool traded)
{
    const QColor base = traded ? clr::SURFACE2 : clr::SURFACE;
    const double lim = 5.0;
    const double t = std::clamp(pct, -lim, lim) / lim; // -1 … 1
    if (std::abs(t) < 0.002) return base;
    const QColor target = t > 0 ? clr::UP : clr::DOWN;
    const double a = 0.25 + std::abs(t) * 0.55;
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
    MarketData::sortByValue(rows);
    double total = 0;
    for (const Stock &s : rows) total += s.val;
    for (const Stock &s : rows) {
        const bool tr = s.traded();
        auto *tile = new QFrame;
        tile->setObjectName(QStringLiteral("tile"));
        tile->setStyleSheet(QStringLiteral("QFrame#tile{background:%1;border:1px solid %2;border-radius:8px;}")
                                .arg(heatColor(s.pct(), tr).name(), tr ? clr::LINE.name() : clr::SURFACE.name()));
        auto *tl = new QVBoxLayout(tile);
        tl->setContentsMargins(8, 4, 8, 4);
        tl->setSpacing(0);
        const QString fg = (tr ? clr::FG : clr::MUTED).name();
        auto *a = lbl(s.sym, QStringLiteral("font-size:9pt;font-weight:bold;color:%1;").arg(fg) + kPlain);
        a->setAlignment(Qt::AlignCenter);
        auto *b = lbl(tr || s.dir() ? pctTxt(s.pct(), s.dir()) : QStringLiteral("لم يُتداول"),
                      QStringLiteral("font-size:8.5pt;font-weight:bold;color:%1;").arg(fg) + kPlain);
        b->setAlignment(Qt::AlignCenter);
        tl->addWidget(a);
        tl->addWidget(b);
        // حد أدنى للعرض حتى تبقى بلاطة السهم غير المتداول مقروءة
        const int stretch = total > 0 ? std::max(4, int(std::lround(s.val / total * 100))) : 1;
        m_heatRow->addWidget(tile, stretch);
    }

    // سطر القطاعات — مرجّح بالقيمة السوقية متى عُرف عدد أسهم كل شركات القطاع، وإلا بأوزان متساوية
    clearLayout(m_sectorsRow);
    m_sectorsRow->addWidget(lbl(QStringLiteral("القطاعات:"),
                                QStringLiteral("font-size:9.5pt;color:%1;").arg(clr::MUTED.name()) + kPlain));
    for (const SectorPerf &p : m_data.sectors()) {
        const int d = p.dir();
        QString extra = QStringLiteral("· %1 متداولة · %2 د.ل")
                            .arg(ltr(QStringLiteral("%1/%2").arg(p.tradedN).arg(p.n)), ltr(fmInt(p.val)));
        if (p.mcapShare > 0)
            extra += QStringLiteral(" · %1 من السوق").arg(ltr(fm(p.mcapShare, 1) + QStringLiteral("%")));
        auto *l = lbl(QStringLiteral("%1%2 %3 <span style='color:%4;font-weight:normal'>%5</span>")
                          .arg(p.name.toHtmlEscaped(), p.capWeighted ? QString() : QStringLiteral("*"),
                               pctTxt(p.avgPct, d), clr::MUTED.name(), extra),
                      QStringLiteral("font-size:9.5pt;font-weight:bold;color:%1;").arg(dirColor(d).name()) + kPlain);
        l->setTextFormat(Qt::RichText);
        m_sectorsRow->addWidget(l);
    }
    m_sectorsRow->addStretch(1);
    bool anyEqual = false;
    for (const SectorPerf &p : m_data.sectors()) anyEqual |= !p.capWeighted;
    if (anyEqual)
        m_sectorsRow->addWidget(lbl(QStringLiteral("* متوسط بأوزان متساوية"),
                                    QStringLiteral("font-size:8.5pt;color:%1;").arg(clr::MUTED.name()) + kPlain));
}
