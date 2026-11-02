"""اختبارات وحدة الربط بقاعدة البيانات: python -m unittest discover -s tests -p "test_*.py" """
import datetime as dt
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import lsm_db_feeder as D  # noqa: E402

SESSION = ROOT / "data" / "session.json"
COMPANIES = ROOT / "data" / "companies.json"

INI = """
[database]
type = sqlite
path = {db}
[queries]
stocks = SELECT * FROM LSM_DISPLAY_V
index  = SELECT * FROM LSM_INDEX_V
[columns]
{columns}
[schedule]
days = sun,mon,tue,wed,thu
open = 10:00
close = 13:00
pre_minutes = 15
post_minutes = 30
interval = 15
heartbeat_seconds = 60
holidays_file = holidays.json
[output]
session = session.json
companies = {companies}
archive_dir = archive
status_file = status.json
[alerts]
enabled = false
stale_minutes = 5
repeat_minutes = 60
"""

SUN_1100 = dt.datetime(2026, 11, 1, 11, 0)       # الأحد — أثناء الجلسة


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.db = self.d / "demo.sqlite"
        D.make_demo_db(self.db, SESSION)
        (self.d / "holidays.json").write_text(json.dumps(
            {"holidays": [{"date": "2026-12-24", "name": "عيد الاستقلال"}]}, ensure_ascii=False), encoding="utf-8")
        self.write_ini()

    def tearDown(self):
        if hasattr(self, "feeder"):
            self.feeder.close()
        self.tmp.cleanup()

    def write_ini(self, columns="", db=None):
        if hasattr(self, "feeder"):
            self.feeder.close()
        (self.d / "db.ini").write_text(INI.format(db=db or self.db, columns=columns, companies=COMPANIES),
                                       encoding="utf-8")
        self.feeder = D.DbFeeder(D.Config(self.d / "db.ini"))
        return self.feeder

    def session(self):
        return json.loads((self.d / "session.json").read_text(encoding="utf-8"))

    def db_exec(self, sql, *args):
        con = sqlite3.connect(self.db)
        con.execute(sql, args)
        con.commit()
        con.close()


class ReadOnlyGuard(unittest.TestCase):
    def test_allows_select(self):
        self.assertTrue(D.check_readonly_sql("SELECT * FROM V;"))
        self.assertTrue(D.check_readonly_sql("WITH x AS (SELECT 1 a) SELECT * FROM x"))
        self.assertTrue(D.check_readonly_sql("SELECT UPDATED_AT, CREATED_BY FROM V WHERE n = 'delete'"))

    def test_rejects_writes(self):
        for sql in ("DELETE FROM prices", "SELECT 1; DROP TABLE prices", "UPDATE prices SET x=1",
                    "SELECT * INTO backup FROM prices", "EXEC sp_who", "/* x */ insert into t values (1)"):
            with self.assertRaises(ValueError, msg=sql):
                D.check_readonly_sql(sql)


class Snapshot(Base):
    def test_tick_writes_session(self):
        self.assertTrue(self.feeder.tick(SUN_1100))
        s = self.session()
        self.assertEqual(s["source"], "قاعدة بيانات نظام التداول")
        self.assertEqual(s["session"]["date"], "2026-11-01")
        self.assertEqual(len(s["stocks"]), 11)
        ncb = next(x for x in s["stocks"] if x["sym"] == "NCB")
        self.assertEqual((ncb["last"], ncb["bid"], ncb["shares"]), (9.1, 8.0, 175000000))
        st = json.loads((self.d / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(st["state"], "ok")
        self.assertEqual(st["warnings"], [])

    def test_live_update_and_index_series(self):
        self.feeder.tick(SUN_1100)
        self.db_exec("UPDATE prices SET LAST_PRICE=12.5, HIGH_PRICE=12.5, LOW_PRICE=12.3, VOLUME=1000, "
                     "TRADE_VALUE=12400, TRADES=4 WHERE SYMBOL='SB'")
        self.db_exec("UPDATE idx SET INDEX_VALUE=1140.10")
        self.feeder.tick(SUN_1100 + dt.timedelta(seconds=15))
        s = self.session()
        sb = next(x for x in s["stocks"] if x["sym"] == "SB")
        self.assertEqual((sb["last"], sb["vol"]), (12.5, 1000))
        self.assertEqual(s["index"]["series"], [1139.04, 1134.57, 1140.1])

    def test_heartbeat(self):
        f = self.feeder
        self.assertTrue(f.write_if_needed(f.snapshot(SUN_1100)[0], SUN_1100))
        same = f.snapshot(SUN_1100)[0]
        self.assertFalse(f.write_if_needed(same, SUN_1100 + dt.timedelta(seconds=20)))
        self.assertTrue(f.write_if_needed(same, SUN_1100 + dt.timedelta(seconds=61)))   # نبضة حياة

    def test_explicit_column_mapping(self):
        con = sqlite3.connect(self.db)
        con.executescript("DROP VIEW LSM_DISPLAY_V; CREATE VIEW LSM_DISPLAY_V AS SELECT SYMBOL AS TICKER, "
                          "PREV_CLOSE AS REF_PX, LAST_PRICE AS PX, VOLUME AS QTY, TRADE_VALUE AS AMT, "
                          "TRADES AS N_DEALS, HIGH_PRICE AS HI, LOW_PRICE AS LO FROM prices;")
        con.close()
        f = self.write_ini("sym = TICKER\nprev = REF_PX\nlast = PX\nvol = QTY\nval = AMT\ntrades = N_DEALS\nhigh = HI\nlow = LO")
        self.assertTrue(f.tick(SUN_1100))
        ncb = next(x for x in self.session()["stocks"] if x["sym"] == "NCB")
        self.assertEqual((ncb["prev"], ncb["last"], ncb["vol"]), (9.7, 9.1, 3058))
        f = self.write_ini("sym = TICKER\nlast = NOT_THERE")
        self.assertFalse(f.tick(SUN_1100))

    def test_failure_keeps_last_good_and_alerts(self):
        self.feeder.tick(SUN_1100)
        good = self.session()
        self.feeder.close()
        self.db.unlink()                                      # انقطاع القاعدة
        t1 = SUN_1100 + dt.timedelta(minutes=1)
        self.assertFalse(self.feeder.tick(t1))
        self.assertEqual(self.session()["stocks"], good["stocks"])
        self.assertEqual(json.loads((self.d / "status.json").read_text(encoding="utf-8"))["state"], "error")
        self.assertNotIn("db-down", self.feeder.alerter.sent)     # قبل مرور 5 دقائق
        self.feeder.tick(SUN_1100 + dt.timedelta(minutes=7))
        self.assertIn("db-down", self.feeder.alerter.sent)
        D.make_demo_db(self.db, SESSION)                       # عودة القاعدة
        self.assertTrue(self.feeder.tick(SUN_1100 + dt.timedelta(minutes=8)))
        self.assertIn("db-up", self.feeder.alerter.sent)
        self.assertIsNone(self.feeder.fail_since)

    def test_after_close_archives(self):
        self.feeder.idle(dt.datetime(2026, 11, 1, 13, 45))
        self.assertTrue((self.d / "archive" / "session-2026-11-01.json").exists())


class ScheduleTests(Base):
    def test_windows(self):
        s = self.feeder.schedule
        self.assertTrue(s.active(dt.datetime(2026, 11, 1, 9, 50)))     # الأحد قبل الافتتاح بـ 10 دقائق
        self.assertFalse(s.active(dt.datetime(2026, 11, 1, 9, 40)))
        self.assertTrue(s.active(dt.datetime(2026, 11, 1, 13, 25)))
        self.assertFalse(s.active(dt.datetime(2026, 11, 1, 13, 35)))
        self.assertFalse(s.active(dt.datetime(2026, 11, 6, 11, 0)))    # الجمعة
        self.assertFalse(s.active(dt.datetime(2026, 12, 24, 11, 0)))   # عطلة
        self.assertTrue(s.in_session(dt.datetime(2026, 11, 2, 12, 59)))
        self.assertEqual(s.next_start(dt.datetime(2026, 11, 5, 14, 0)), dt.datetime(2026, 11, 8, 9, 45))

    def test_holiday_closes_and_restores(self):
        self.feeder.tick(SUN_1100)
        self.feeder.idle(dt.datetime(2026, 12, 24, 9, 0))
        s = self.session()["session"]
        self.assertEqual((s["status"], s["holiday"]), ("closed", "عيد الاستقلال"))
        self.feeder.idle(dt.datetime(2026, 12, 27, 8, 0))
        s = self.session()["session"]
        self.assertEqual(s["status"], "auto")
        self.assertNotIn("holiday", s)


class AlertThrottle(unittest.TestCase):
    def test_repeat_suppressed(self):
        tmp = tempfile.TemporaryDirectory()
        p = Path(tmp.name) / "a.ini"
        p.write_text("[alerts]\nenabled=false\nrepeat_minutes=60\n", encoding="utf-8")
        a = D.Alerter(D.Config(p))
        t = dt.datetime(2026, 11, 1, 11, 0)
        self.assertTrue(a.send("k", "s", "b", t))
        self.assertFalse(a.send("k", "s", "b", t + dt.timedelta(minutes=30)))
        self.assertTrue(a.send("k", "s", "b", t + dt.timedelta(minutes=61)))
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
