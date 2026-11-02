"""اختبارات منظومة التغذية: python -m unittest discover -s tests -p "test_feeder.py" """
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import lsm_feeder as F  # noqa: E402

FIXTURE_PDF = ROOT / "tests" / "fixtures" / "trading-report-2026-11-01.pdf"
COMPANIES = json.loads((ROOT / "data" / "companies.json").read_text(encoding="utf-8"))["companies"]


def has_module(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


class Helpers(unittest.TestCase):
    def test_to_num(self):
        self.assertEqual(F.to_num("1,250.5"), 1250.5)
        self.assertEqual(F.to_num("١٬٢٥٠٫٥"), 1250.5)
        self.assertEqual(F.to_num("(12.5)"), -12.5)
        self.assertEqual(F.to_num("-6.19"), -6.19)
        self.assertIsNone(F.to_num("—"))
        self.assertIsNone(F.to_num("دينار ليبي"))
        self.assertEqual(F.to_num(7), 7.0)

    def test_presentation_forms_normalised(self):
        # أشكال العرض كما تخرج من PDF: «ﺔ» و «ﻹ» و «ﳌ»
        self.assertEqual(F.norm_header("سعر اﻹغﻼق"), F.norm_header("سعر الإغلاق"))
        self.assertEqual(F.clean("التنميﺔ"), "التنمية")

    def test_name_matching(self):
        d = F.Directory(COMPANIES)
        self.assertEqual(d.resolve({"en": "National Commercial Bank"}), "NCB")
        self.assertEqual(d.resolve({"name": "مصرف التجاري الوطني"}), "NCB")      # دون «ال»
        self.assertEqual(d.resolve({"name": "شركﺔ الصحاري للتامين"}), "SIC")     # همزة/ياء/تاء مربوطة
        self.assertEqual(d.resolve({"name_candidates": ["ىراحصلا فرصم", "مصرف الصحارى"]}), "SB")
        self.assertIsNone(d.resolve({"en": "New Company"}))


@unittest.skipUnless(FIXTURE_PDF.exists() and (has_module("pdfplumber") or __import__("shutil").which("pdftotext")),
                     "يحتاج pdfplumber أو pdftotext")
class OfficialPdfReport(unittest.TestCase):
    """التقرير الرسمي لجلسة 2026-11-01 — يجب أن تتطابق كل الإجماليات."""

    def setUp(self):
        self.rep = F.parse_report(FIXTURE_PDF)

    def test_parsed_fields(self):
        r = self.rep
        self.assertEqual(r.date, "2026-11-01")
        self.assertEqual(len(r.rows), 11)
        self.assertEqual(r.index["close"], 1134.57)
        self.assertEqual(r.index["open"], 1139.04)
        self.assertEqual(r.totals["mcap"], 11268446000)
        ncb = next(x for x in r.rows if x["en"] == "National Commercial Bank")
        self.assertEqual((ncb["open"], ncb["last"], ncb["pct"], ncb["vol"], ncb["trades"], ncb["bid"], ncb["ask"]),
                         (9.70, 9.10, -6.19, 3058, 3, 8.00, 9.10))

    def test_session_reconciles_with_report(self):
        s, w = F.build_session(self.rep, COMPANIES, None, source="t.pdf")
        self.assertEqual([x for x in w], [])                               # لا تحذيرات ولا فروق
        by = {x["sym"]: x for x in s["stocks"]}
        self.assertEqual(len(by), 11)
        self.assertEqual(by["NCB"]["prev"], 9.70)
        self.assertEqual(by["NCB"]["val"], 27827.8)                        # القيمة الدقيقة لا المقرّبة
        self.assertEqual(by["BCD"]["last"], 42.0)                          # سعر الإغلاق لم يتغير رغم تنفيذ عند 41
        self.assertEqual(by["SIC"]["shares"], 1730000)
        self.assertEqual(sum(x["shares"] * x["last"] for x in s["stocks"]), 11268446000)
        self.assertEqual(s["index"]["value"], 1134.57)
        self.assertEqual(s["index"]["prev"], 1139.04)
        self.assertEqual(s["session"]["date"], "2026-11-01")


class Build(unittest.TestCase):
    def test_prev_from_pct_prefers_open(self):
        self.assertEqual(F._derive_prev({"pct": -6.19, "open": 9.70}, 9.10), 9.70)
        self.assertEqual(F._derive_prev({"pct": 0.0, "open": 42.0}, 42.0), 42.0)
        self.assertAlmostEqual(F._derive_prev({"pct": 10.0}, 11.0), 10.0)

    def test_carry_forward_and_intraday_series(self):
        previous = {"session": {"date": "2026-11-01"},
                    "index": {"value": 1134.57, "prev": 1139.04, "series": [1139.04, 1134.57]},
                    "stocks": [{"sym": "LIC", "prev": 9.4, "last": 9.5}]}
        rows = [{"sym": "NCB", "prev": 9.7, "high": 9.1, "low": 9.1, "last": 9.1, "vol": 3058, "val": 27828, "trades": 3}]
        s, w = F.build_session(rows, COMPANIES, previous, "2026-11-02", 1136.0, None)
        lic = next(x for x in s["stocks"] if x["sym"] == "LIC")
        self.assertEqual((lic["prev"], lic["last"], lic["vol"], lic["shares"]), (9.5, 9.5, 0, 7000000))
        self.assertEqual(s["index"]["series"], [1134.57, 1136.0])
        ncb = next(x for x in s["stocks"] if x["sym"] == "NCB")
        self.assertEqual(ncb["val"], 27827.8)
        s2, _ = F.build_session(rows, COMPANIES, s, "2026-11-02", 1137.2, None)
        self.assertEqual(s2["index"]["series"], [1134.57, 1136.0, 1137.2])
        self.assertEqual(s2["index"]["prev"], 1134.57)

    def test_share_change_warned(self):
        rows = [{"en": "Wahda bank", "last": 14.51, "pct": 0, "mcap": 14.51 * 170000000}]
        s, w = F.build_session(rows, COMPANIES, None, "2026-11-02")
        self.assertEqual(next(x for x in s["stocks"] if x["sym"] == "WB")["shares"], 170000000)
        self.assertTrue(any("يختلف عن الملف المرجعي" in x for x in w))

    def test_unknown_company_gets_temp_symbol(self):
        rows = [{"en": "Al Waha Oil Services", "last": 5.0, "pct": 0}]
        s, w = F.build_session(rows, COMPANIES, None, "2026-11-02")
        self.assertIn("AWOS", [x["sym"] for x in s["stocks"]])
        self.assertTrue(any("غير معرّفة" in x for x in w))

    def test_reconcile_detects_mismatch(self):
        rep = F.Report()
        rep.rows = [{"sym": "NCB", "last": 9.1, "pct": -6.19, "open": 9.7, "vol": 100, "val": 910, "trades": 1}]
        rep.totals = {"val": 1000.0}
        rep.breadth = {"down": 2}
        _, w = F.build_session(rep, COMPANIES, None, "2026-11-02")
        self.assertTrue(any("قيمة التداول" in x for x in w))
        self.assertTrue(any("المنخفضة" in x for x in w))

    def test_close_held_not_flagged(self):
        self.assertEqual(F.sanity_checks([{"sym": "BCD", "prev": 42, "last": 42, "high": 41, "low": 41,
                                           "vol": 213, "val": 8733}]), [])
        self.assertTrue(F.sanity_checks([{"sym": "X", "prev": 40, "last": 42, "high": 41, "low": 41,
                                          "vol": 213, "val": 8733}]))


@unittest.skipUnless(has_module("openpyxl"), "يحتاج openpyxl")
class OfficialExcelLayout(unittest.TestCase):
    """ملف Excel بتخطيط التقرير الرسمي (عناوين على عدة أسطر، أسطر قطاعات وإجماليات، كتلة المؤشر)."""

    def make(self, d: Path) -> Path:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append([None, None, None, None, None, None, None, None, None, None, None, None, "2026-11-01",
                   "تقرير عمليات التداول بسوق المال الليبي عن يوم الأحد"])
        ws.append(["القيمة السوقية / دينار", "أفضل عرض", "أفضل طلب", "عدد العمليات", "قيمة التداول", "كمية التداول",
                   "التغير %", "سعر الإغلاق", "أعلى سعر", "أقل سعر", "سعر الفتح", "عملة", "Company", "الجهة"])
        ws.append(["Market Cap D.L", "best offer", "best bid", "no. of trades", "trading value", "trading volume",
                   "change %", "close price", "high price", "low price", "open price", "currency", None, None])
        ws.append([None] * 6 + ["قطاع المصارف banks sector"])
        ws.append([1592500000, 9.10, 8.00, 3, 27827.8, 3058, -6.19, 9.10, 9.10, 9.10, 9.70, "دينار ليبي",
                   "National Commercial Bank", "مصرف التجاري الوطني"])
        ws.append([2250000000, 8.00, 7.40, 3, 38557.5, 5141, 0, 7.50, 7.50, 7.50, 7.50, "دينار ليبي",
                   "Gumhouria Bank", "مصرف الجمهورية"])
        ws.append([3842500000, None, None, 6, 66385.3, 8199, None, None, None, None, None, None, None,
                   "إجمالي قطاع المصارف Total banks Sector"])
        ws.append([3842500000, None, None, 6, 66385.3, 8199, None, None, None, None, None, None, None,
                   "إجمالي السوق Market Total"])
        ws.append([])
        ws.append(["أدنى", "أعلى", "التغير", None, "الإغلاق", "الفتح", "المؤشر Index", None, 2, "عدد الشركات المتداولة"])
        ws.append(["Low", "High", "%", "نقاط / Point", "Close", "Open", None, None, 0, "عدد الشركات المرتفعة"])
        ws.append([1134.57, 1139.04, -0.39, -4.47, 1134.57, 1139.04, None, None, 1, "عدد الشركات المنخفضة"])
        p = d / "تقرير عمليات التداول 01-11-2026.xlsx"
        wb.save(p)
        return p

    def test_excel(self):
        with tempfile.TemporaryDirectory() as d:
            rep = F.parse_report(self.make(Path(d)))
            self.assertEqual(rep.date, "2026-11-01")
            self.assertEqual(len(rep.rows), 2)
            self.assertEqual(rep.rows[0]["en"], "National Commercial Bank")
            self.assertEqual(rep.rows[0]["sector"], "المصارف")
            self.assertEqual(rep.index["close"], 1134.57)
            self.assertEqual(rep.index["open"], 1139.04)
            self.assertEqual(rep.totals["val"], 66385.3)
            self.assertEqual(rep.breadth, {"traded": 2, "up": 0, "down": 1})
            only = [c for c in COMPANIES if c["sym"] in ("NCB", "GB")]
            s, w = F.build_session(rep, only, None)
            self.assertEqual(w, [])
            self.assertEqual([x["sym"] for x in s["stocks"]], ["NCB", "GB"])


class EndToEnd(unittest.TestCase):
    def test_csv_with_symbols(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rep = d / "report.csv"
            with open(rep, "w", newline="", encoding="cp1256") as f:          # ترميز ويندوز العربي
                wr = csv.writer(f, delimiter=";")
                wr.writerow(["الرمز", "إغلاق سابق", "الأعلى", "الأدنى", "آخر سعر", "الكمية", "القيمة", "الصفقات"])
                wr.writerow(["NCB", "9.700", "9.100", "9.100", "9.100", "3,058", "27,827.8", "3"])
                wr.writerow(["", "", "", "", "", "3058", "27827.8", "3"])
            out = d / "session.json"
            rc = F.main([str(rep), "--out", str(out), "--companies", str(ROOT / "data" / "companies.json"),
                         "--date", "2026-11-02", "--index", "1134.57", "--index-prev", "1139.04"])
            self.assertEqual(rc, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual([s["sym"] for s in data["stocks"]], ["NCB"])
            self.assertEqual(list(d.glob(".session-*")), [])


if __name__ == "__main__":
    unittest.main()
