/* ═══════════════════════════════════════════════════════════════════════════
   شاشة عرض أسهم سوق المال الليبي — تجهيز القراءة من قاعدة بيانات نظام التداول
   Oracle — يُنفّذه مسؤول قاعدة البيانات (DBA) مرة واحدة.

   ⚠ أسماء الجداول والأعمدة بين < > افتراضية ويستبدلها مسؤول القاعدة بالأسماء الفعلية.
     أسماء أعمدة جدول العرض (بعد AS) تبقى كما هي.
   ═══════════════════════════════════════════════════════════════════════════ */

-- ① جدول عرض الأسعار
CREATE OR REPLACE VIEW TRADING.LSM_DISPLAY_V AS
SELECT
    s.SYMBOL              AS SYMBOL,
    s.PREV_CLOSE          AS PREV_CLOSE,
    s.OPEN_PRICE          AS OPEN_PRICE,
    s.HIGH_PRICE          AS HIGH_PRICE,
    s.LOW_PRICE           AS LOW_PRICE,
    s.CLOSE_PRICE         AS LAST_PRICE,
    s.TRADED_VOLUME       AS VOLUME,
    s.TRADED_VALUE        AS TRADE_VALUE,
    s.TRADES_COUNT        AS TRADES,
    ob.BEST_BID           AS BEST_BID,
    ob.BEST_ASK           AS BEST_ASK,
    s.SHARES_OUTSTANDING  AS SHARES_OUTSTANDING
FROM TRADING.<جدول_ملخص_الجلسة_لكل_سهم> s
LEFT JOIN TRADING.<جدول_أفضل_الأسعار> ob ON ob.SYMBOL = s.SYMBOL
WHERE s.SESSION_DATE = (SELECT MAX(SESSION_DATE) FROM TRADING.<جدول_ملخص_الجلسة_لكل_سهم>);

-- ② جدول عرض المؤشر (سطر واحد)
CREATE OR REPLACE VIEW TRADING.LSM_INDEX_V AS
SELECT SESSION_DATE, INDEX_VALUE, INDEX_PREV, INDEX_HIGH, INDEX_LOW FROM (
    SELECT i.SESSION_DATE AS SESSION_DATE, i.INDEX_VALUE AS INDEX_VALUE, i.PREV_CLOSE AS INDEX_PREV,
           i.HIGH_VALUE AS INDEX_HIGH, i.LOW_VALUE AS INDEX_LOW
    FROM TRADING.<جدول_المؤشر> i ORDER BY i.SESSION_DATE DESC
) WHERE ROWNUM = 1;

-- ③ حساب للقراءة فقط
CREATE USER LSM_DISPLAY_RO IDENTIFIED BY "<كلمة_مرور_قوية>";
GRANT CREATE SESSION TO LSM_DISPLAY_RO;
GRANT SELECT ON TRADING.LSM_DISPLAY_V TO LSM_DISPLAY_RO;
GRANT SELECT ON TRADING.LSM_INDEX_V   TO LSM_DISPLAY_RO;
-- (لا تُمنح أي صلاحية أخرى)

-- في db_feeder.ini تُكتب الاستعلامات باسم المخطط:
--   stocks = SELECT * FROM TRADING.LSM_DISPLAY_V
--   index  = SELECT * FROM TRADING.LSM_INDEX_V
