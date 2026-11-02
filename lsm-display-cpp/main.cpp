// شاشة عرض أسهم سوق المال الليبي — تطبيق مكتبي بلغة C++ / Qt
#include <QApplication>
#include <QCommandLineParser>
#include <QFont>
#include <QFontDatabase>
#include "DisplayWindow.h"

int main(int argc, char *argv[])
{
    // مقياس العرض لشاشات القاعة الكبيرة (مثلاً --scale 1.5 لشاشة 4K) — يجب ضبطه قبل إنشاء التطبيق
    for (int i = 1; i + 1 < argc; ++i)
        if (qstrcmp(argv[i], "--scale") == 0)
            qputenv("QT_SCALE_FACTOR", QByteArray(argv[i + 1]));
#if QT_VERSION < QT_VERSION_CHECK(6, 0, 0)
    QApplication::setAttribute(Qt::AA_EnableHighDpiScaling);
    QApplication::setAttribute(Qt::AA_UseHighDpiPixmaps);
#endif

    QApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("LSM Market Display"));
    app.setApplicationVersion(QStringLiteral("1.1"));
    app.setOrganizationName(QStringLiteral("Libyan Stock Market"));
    app.setLayoutDirection(Qt::RightToLeft);

    QCommandLineParser cli;
    cli.setApplicationDescription(QStringLiteral("شاشة عرض أسهم سوق المال الليبي"));
    cli.addHelpOption();
    cli.addVersionOption();
    QCommandLineOption optFull({QStringLiteral("f"), QStringLiteral("fullscreen")},
                               QStringLiteral("التشغيل مباشرة في وضع القاعة (ملء الشاشة وإخفاء المؤشر)."));
    QCommandLineOption optData({QStringLiteral("d"), QStringLiteral("data")},
                               QStringLiteral("مسار ملف بيانات الجلسة."), QStringLiteral("file"));
    QCommandLineOption optPoll(QStringLiteral("poll"),
                               QStringLiteral("فترة فحص تعديل الملف بالثواني (افتراضي 5)."), QStringLiteral("sec"), QStringLiteral("5"));
    QCommandLineOption optStale(QStringLiteral("stale"),
                                QStringLiteral("دقائق بلا تحديث أثناء الجلسة قبل إظهار التنبيه (افتراضي 10)."), QStringLiteral("min"), QStringLiteral("10"));
    QCommandLineOption optPage(QStringLiteral("page"),
                               QStringLiteral("ثواني التمرير الآلي للجدول (افتراضي 8)."), QStringLiteral("sec"), QStringLiteral("8"));
    QCommandLineOption optScale(QStringLiteral("scale"),
                                QStringLiteral("مقياس تكبير الواجهة لشاشات القاعة (مثلاً 1.5)."), QStringLiteral("factor"));
    QCommandLineOption optShot(QStringLiteral("snapshot"),
                               QStringLiteral("حفظ صورة PNG للشاشة ثم الخروج (للنشر أو التحقق)."), QStringLiteral("png"));
    cli.addOptions({optFull, optData, optPoll, optStale, optPage, optScale, optShot});
    cli.process(app);

    // Tahoma متوفر على ويندوز؛ على الأنظمة الأخرى يُختار أول خط عربي متاح
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
    const QStringList fams = QFontDatabase::families();
#else
    const QStringList fams = QFontDatabase().families();
#endif
    QFont f(QStringLiteral("Tahoma"));
    if (!fams.contains(QStringLiteral("Tahoma"))) {
        for (const char *alt : {"Noto Sans Arabic", "Noto Naskh Arabic", "DejaVu Sans"})
            if (fams.contains(QString::fromLatin1(alt))) { f = QFont(QString::fromLatin1(alt)); break; }
    }
    f.setPointSizeF(10.5);
    app.setFont(f);

    DisplayOptions opt;
    opt.fullscreen   = cli.isSet(optFull);
    opt.dataPath     = cli.value(optData);
    opt.pollMs       = qMax(1, cli.value(optPoll).toInt()) * 1000;
    opt.staleMinutes = qMax(1, cli.value(optStale).toInt());
    opt.pageSeconds  = qMax(3, cli.value(optPage).toInt());
    opt.snapshotPath = cli.value(optShot);

    DisplayWindow w(opt);
    w.start();
    return app.exec();
}
