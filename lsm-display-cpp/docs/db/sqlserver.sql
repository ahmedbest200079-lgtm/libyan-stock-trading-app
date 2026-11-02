/* ═══════════════════════════════════════════════════════════════════════════
   شاشة عرض أسهم سوق المال الليبي — تجهيز القراءة من قاعدة بيانات نظام التداول
   SQL Server — يُنفّذه مسؤول قاعدة البيانات (DBA) مرة واحدة.

   ⚠ أسماء الجداول والأعمدة في الطرف الأيمن من كل سطر (dbo.<...>) افتراضية:
     يستبدلها مسؤول القاعدة بالأسماء الفعلية في نظام التداول. يجب أن تبقى
     أسماء أعمدة جدول العرض (يسار AS) كما هي.
   ═══════════════════════════════════════════════════════════════════════════ */

-- ① جدول عرض الأسعار: سطر لكل شركة مدرجة، بأرقام الجلسة الحالية
CREATE OR ALTER VIEW dbo.LSM_DISPLAY_V AS
SELECT
    s.SYMBOL                AS SYMBOL,              -- رمز الشركة (مطابق لـ companies.json)
    s.PREV_CLOSE            AS PREV_CLOSE,          -- سعر الإغلاق السابق (المرجعي)
    s.OPEN_PRICE            AS OPEN_PRICE,          -- سعر الفتح
    s.HIGH_PRICE            AS HIGH_PRICE,          -- أعلى سعر (0 أو NULL إن لم يُتداول)
    s.LOW_PRICE             AS LOW_PRICE,           -- أقل سعر
    s.CLOSE_PRICE           AS LAST_PRICE,          -- آخر سعر / سعر الإغلاق المعتمد
    s.TRADED_VOLUME         AS VOLUME,              -- كمية التداول
    s.TRADED_VALUE          AS TRADE_VALUE,         -- قيمة التداول (د.ل)
    s.TRADES_COUNT          AS TRADES,              -- عدد العمليات
    ob.BEST_BID             AS BEST_BID,            -- أفضل طلب
    ob.BEST_ASK             AS BEST_ASK,            -- أفضل عرض
    s.SHARES_OUTSTANDING    AS SHARES_OUTSTANDING   -- عدد الأسهم المصدرة (اختياري)
FROM dbo.<جدول_ملخص_الجلسة_لكل_سهم>  s
LEFT JOIN dbo.<جدول_أفضل_الأسعار> ob ON ob.SYMBOL = s.SYMBOL
WHERE s.SESSION_DATE = (SELECT MAX(SESSION_DATE) FROM dbo.<جدول_ملخص_الجلسة_لكل_سهم>);
GO

-- ② جدول عرض المؤشر: سطر واحد
CREATE OR ALTER VIEW dbo.LSM_INDEX_V AS
SELECT TOP (1)
    i.SESSION_DATE          AS SESSION_DATE,
    i.INDEX_VALUE           AS INDEX_VALUE,         -- القيمة الحالية / الإغلاق
    i.PREV_CLOSE            AS INDEX_PREV,          -- إغلاق الجلسة السابقة
    i.HIGH_VALUE            AS INDEX_HIGH,
    i.LOW_VALUE             AS INDEX_LOW
FROM dbo.<جدول_المؤشر> i
ORDER BY i.SESSION_DATE DESC;
GO

-- ③ حساب للقراءة فقط مقصور على جدولي العرض — دون أي صلاحية على الجداول الأصلية
CREATE LOGIN lsm_display_ro WITH PASSWORD = '<كلمة_مرور_قوية>', CHECK_POLICY = ON;
CREATE USER  lsm_display_ro FOR LOGIN lsm_display_ro;
GRANT SELECT ON dbo.LSM_DISPLAY_V TO lsm_display_ro;
GRANT SELECT ON dbo.LSM_INDEX_V   TO lsm_display_ro;
DENY  INSERT, UPDATE, DELETE, EXECUTE TO lsm_display_ro;
GO

-- ④ تحقق: يجب أن يعيد سطرًا لكل شركة مدرجة
-- EXECUTE AS USER = 'lsm_display_ro'; SELECT * FROM dbo.LSM_DISPLAY_V; SELECT * FROM dbo.LSM_INDEX_V; REVERT;
