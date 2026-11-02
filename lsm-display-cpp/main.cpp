// شاشة عرض أسهم سوق المال الليبي — تطبيق مكتبي بلغة C++ / Qt
#include <QApplication>
#include <QFont>
#include "DisplayWindow.h"

int main(int argc, char *argv[])
{
    QApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("LSM Market Display"));
    app.setOrganizationName(QStringLiteral("Libyan Stock Market"));
    app.setLayoutDirection(Qt::RightToLeft);

    // Tahoma متوفر على ويندوز؛ على الأنظمة الأخرى يُستخدم البديل المتاح
    QFont f(QStringLiteral("Tahoma"));
    f.setPointSizeF(10.5);
    app.setFont(f);

    DisplayWindow w;
    w.show();
    return app.exec();
}
