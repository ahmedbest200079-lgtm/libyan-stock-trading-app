"""اختبارات منظومة التغذية: python -m unittest discover -s tests -p 'test_feeder.py'"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import lsm_feeder as F  # noqa: E402

COMPANIES = [
    {"sym": "NCB", "name": "المصرف التجاري الوطني", "sector": "المصارف", "shares": 1000000},
    {"sym": "GB", "name": "مصرف الجمهورية", "sector": "المصارف", "shares": None},
    {"sym": "LIC", "name": "شركة ليبيا للتأمين", "sector": "التأمين", "shares": 200000},
]


class Helpers(unittest.TestCase):
    def test_to_num(self):
        self.assertEqual(F.to_num("1,250.5"), 1250.5)
        self.assertEqual(F.to_num("١٬٢٥٠٫٥"), 1250.5)
        self.assertEqual(F.to_num("(12.5)"), -12.5)
        self.assertIsNone(F.to_num("—"))
        self.assertIsNone(F.to_num(""))
        self.assertEqual(F.to_num(7), 7.0)

    def test_header_aliases(self):
        rows = [["تقرير التداول اليومي"], [],
                ["رمز السهم", "اسم الشركة", "سعر الإغلاق السابق", "أعلى سعر", "أدنى سعر", "سعر الإغلاق",
                 "الكمية المتداولة", "قيمة التداول", "عدد الصفقات"]]
        i, m = F.find_header(rows)
        self.assertEqual(i, 2)
        self.assertEqual(m["sym"], 0)
        self.assertEqual(m["last"], 5)
        self.assertEqual(m["trades"], 8)
        _, m2 = F.find_header([["Symbol", "Prev Close", "Close", "Volume", "Turnover", "Deals"]])
        self.assertEqual((m2["prev"], m2["last"], m2["vol"], m2["val"], m2["trades"]), (1, 2, 3, 4, 5))


class Build(unittest.TestCase):
    def test_merge_reference_and_carry_forward(self):
        previous = {"session": {"date": "2026-11-01"},
                    "index": {"value": 1134.57, "prev": 1139.04, "series": [1139.04, 1134.57]},
                    "stocks": [{"sym": "LIC", "prev": 9.4, "last": 9.5, "sector": "التأمين"}]}
        report = [{"sym": "NCB", "prev": 9.7, "high": 9.1, "low": 9.1, "last": 9.1, "vol": 3058, "val": 27828, "trades": 3}]
        s, w = F.build_session(report, COMPANIES, previous, "2026-11-02", 1136.0, None)
        syms = [x["sym"] for x in s["stocks"]]
        self.assertEqual(syms, ["NCB", "LIC"])                       # GB بلا سعر سابق ← يُستبعد مع تحذير
        lic = s["stocks"][1]
        self.assertEqual((lic["prev"], lic["last"], lic["vol"]), (9.5, 9.5, 0))   # ترحيل آخر سعر
        self.assertEqual(lic["shares"], 200000)
        self.assertEqual(s["stocks"][0]["shares"], 1000000)
        self.assertEqual(s["index"]["prev"], 1134.57)                 # جلسة جديدة: السابق = آخر قيمة
        self.assertEqual(s["index"]["series"], [1134.57, 1136.0])
        self.assertTrue(any("GB" in x for x in w))

    def test_intraday_series_appends(self):
        prev = {"session": {"date": "2026-11-02"}, "index": {"value": 1136.0, "prev": 1134.57, "series": [1134.57, 1136.0]},
                "stocks": []}
        s, _ = F.build_session([{"sym": "NCB", "prev": 9.7, "last": 9.7}], COMPANIES, prev, "2026-11-02", 1137.2, None)
        self.assertEqual(s["index"]["prev"], 1134.57)
        self.assertEqual(s["index"]["series"], [1134.57, 1136.0, 1137.2])
        s2, _ = F.build_session([{"sym": "NCB", "prev": 9.7, "last": 9.7}], COMPANIES, s, "2026-11-02", 1137.2, None)
        self.assertEqual(len(s2["index"]["series"]), 3)                 # قيمة مكررة لا تُضاف

    def test_sanity_flags_out_of_range(self):
        w = F.sanity_checks([{"sym": "BCD", "prev": 42, "last": 42, "high": 41, "low": 41, "vol": 213, "val": 8733}])
        self.assertTrue(any("خارج نطاق" in x for x in w))


class EndToEnd(unittest.TestCase):
    def test_csv_to_session_file(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "companies.json").write_text(json.dumps({"companies": COMPANIES}, ensure_ascii=False), encoding="utf-8")
            rep = d / "report.csv"
            with open(rep, "w", newline="", encoding="cp1256") as f:      # ترميز ويندوز العربي
                wr = csv.writer(f, delimiter=";")
                wr.writerow(["الرمز", "الشركة", "إغلاق سابق", "الأعلى", "الأدنى", "آخر سعر", "الكمية", "القيمة", "الصفقات"])
                wr.writerow(["NCB", "المصرف التجاري الوطني", "9.700", "9.100", "9.100", "9.100", "3,058", "27,828", "3"])
                wr.writerow(["GB", "مصرف الجمهورية", "7.5", "7.5", "7.5", "7.5", "5141", "38558", "3"])
                wr.writerow(["", "الإجمالي", "", "", "", "", "8199", "66386", "6"])
            out = d / "session.json"
            rc = F.main([str(rep), "--out", str(out), "--companies", str(d / "companies.json"),
                         "--date", "2026-11-02", "--index", "1134.57", "--index-prev", "1139.04"])
            self.assertEqual(rc, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(data["demo"])
            by = {s["sym"]: s for s in data["stocks"]}
            self.assertEqual(set(by), {"NCB", "GB"})                      # LIC بلا سعر ولا جلسة سابقة
            self.assertEqual(by["NCB"]["vol"], 3058)
            self.assertNotIn("shares", by["GB"])
            self.assertEqual(list(d.glob(".session-*")), [])            # لا ملفات مؤقتة متبقية

    def test_xlsx(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl غير مثبت")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            wb = openpyxl.Workbook()
            wb.active.title = "ملخص"
            ws = wb.create_sheet("الأسهم")
            ws.append(["Symbol", "Prev Close", "Close", "Volume", "Turnover", "Deals"])
            ws.append(["NCB", 9.7, 9.1, 3058, 27828, 3])
            wb.save(d / "r.xlsx")
            rows = F.parse_report(d / "r.xlsx")
            self.assertEqual(rows[0]["sym"], "NCB")
            self.assertEqual(rows[0]["last"], 9.1)


if __name__ == "__main__":
    unittest.main()
