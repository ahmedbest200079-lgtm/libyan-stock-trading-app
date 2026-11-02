#!/usr/bin/env python3
"""
منظومة التغذية — تحويل «تقرير عمليات التداول» اليومي لسوق المال الليبي إلى ملف شاشة العرض data/session.json

يقبل التقرير بصيغه الثلاث:
  - Excel ‏(.xlsx) — الملف الأصلي الذي يُعِدّه قسم المؤشرات والتقارير
  - PDF — النسخة المطبوعة الموزّعة (Microsoft Print to PDF)
  - CSV — أي تصدير جدولي

الاستخدام:
  python lsm_feeder.py "تقرير عمليات التداول 01-11-2026.pdf"
  python lsm_feeder.py report.xlsx --dry-run              # عرض النتيجة والتحقق دون كتابة
  python lsm_feeder.py --watch "D:\\LSM\\reports"           # تحويل كل تقرير جديد يُحفظ في المجلد

ما يُستخرج من التقرير تلقائيًا:
  - أسعار كل شركة (الفتح/الأعلى/الأدنى/الإغلاق/التغير%) والكمية والقيمة وعدد العمليات وأفضل طلب/عرض
  - تاريخ الجلسة، وقيم المؤشر (الفتح/الإغلاق/الأعلى/الأدنى)
  - عدد الأسهم المصدرة = القيمة السوقية ÷ سعر الإغلاق (يُقارن بالملف المرجعي)
  - إجماليات التقرير وعدد الشركات المرتفعة/المنخفضة/الثابتة — تُستخدم للمطابقة مع ما تحسبه الشاشة

التقرير لا يحتوي عمود رمز؛ تُطابق الشركات بالاسم الإنجليزي أو العربي عبر data/companies.json
(حقول en و aliases). شركة جديدة غير معرّفة تُضاف برمز مؤقت مع تحذير لإضافتها إلى الملف المرجعي.

المتطلبات: بايثون 3.8+، و openpyxl لملفات Excel، و pdfplumber لملفات PDF:
  pip install openpyxl pdfplumber
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = HERE.parent / "data"

# ───────────────────────── تطبيع النصوص والأرقام ─────────────────────────
_BIDI = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_TASHKEEL = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u0640]")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
_ARABIC = re.compile(r"[\u0600-\u06FF]")


def clean(s) -> str:
    """NFKC يحوّل أشكال العرض العربية (ﺔ ﻹ ﳌ…) إلى الحروف الأصلية، ثم إزالة علامات الاتجاه والتشكيل."""
    s = unicodedata.normalize("NFKC", str(s if s is not None else ""))
    return _TASHKEEL.sub("", _BIDI.sub("", s)).strip()


def _unify(s: str) -> str:
    s = clean(s).lower()
    return (s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
             .replace("ة", "ه").replace("ى", "ي"))


def norm_header(s) -> str:
    return re.sub(r"[\s_\-:()\./\\،,]+", "", _unify(s))


def norm_name(s) -> str:
    return re.sub(r"[^\w&]+", "", _unify(s))


def strip_al(key: str) -> str:
    """مفتاح بديل دون «ال» التعريف — يطابق «مصرف التجاري الوطني» مع «المصرف التجاري الوطني»."""
    return re.sub(r"(^|(?<=\s))ال", "", key)


def to_num(v):
    """يحوّل '1,250.5' أو '١٬٢٥٠٫٥' أو '(12.5)' إلى رقم؛ يعيد None للخانة الفارغة أو غير الرقمية."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if hasattr(v, "__float__") and not isinstance(v, str):     # Decimal من قواعد البيانات
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    s = clean(v).translate(_AR_DIGITS).replace("\u066a", "%").strip()
    if s in ("", "-", "—", "–", "N/A", "n/a"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s2 = re.sub(r"[%\s()]", "", s.replace(",", ""))
    if not re.fullmatch(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?", s2):
        return None
    x = float(s2)
    return -x if neg else x


# ───────────────────────── أسماء الأعمدة ─────────────────────────
COLUMN_ALIASES: dict[str, list[str]] = {
    "sym":    ["الرمز", "رمز السهم", "رمز الشركة", "sym", "symbol", "ticker", "code"],
    "name":   ["الجهة", "الشركة", "اسم الشركة", "اسم السهم", "name"],
    "en":     ["company", "company name"],
    "sector": ["القطاع", "sector"],
    "prev":   ["إغلاق سابق", "الإغلاق السابق", "سعر الإغلاق السابق", "السعر المرجعي", "prev", "previous close", "prev close", "reference price"],
    "open":   ["سعر الفتح", "الافتتاح", "سعر الافتتاح", "الفتح", "open", "open price"],
    "high":   ["أعلى سعر", "الأعلى", "high", "high price"],
    "low":    ["أقل سعر", "أدنى سعر", "الأدنى", "low", "low price"],
    "last":   ["سعر الإغلاق", "آخر سعر", "الإغلاق", "close", "close price", "last", "last price"],
    "pct":    ["التغير %", "التغير٪", "نسبة التغير", "change %", "change%", "% change"],
    "vol":    ["كمية التداول", "الكمية", "الكمية المتداولة", "حجم التداول", "trading volume", "vol", "volume", "quantity", "qty"],
    "val":    ["قيمة التداول", "القيمة", "القيمة المتداولة", "القيمة (د.ل)", "trading value", "trade value", "traded value", "value traded", "val", "value", "turnover"],
    "trades": ["عدد العمليات", "الصفقات", "عدد الصفقات", "no. of trades", "no of trades", "trades", "deals", "transactions"],
    "bid":    ["أفضل طلب", "best bid", "bid"],
    "ask":    ["أفضل عرض", "best offer", "best ask", "offer", "ask"],
    "mcap":   ["القيمة السوقية / دينار", "القيمة السوقية", "market cap d.l", "market cap", "market capitalization"],
    "shares": ["عدد الأسهم المصدرة", "الأسهم المصدرة", "shares", "shares outstanding", "issued shares"],
}
NUMERIC = ("prev", "open", "high", "low", "last", "pct", "vol", "val", "trades", "bid", "ask", "mcap", "shares")
_ALIAS_LOOKUP = {norm_header(a): field for field, names in COLUMN_ALIASES.items() for a in names}

# ترتيب الأرقام في سطر الشركة كما يظهر في نسخة PDF من التقرير الرسمي (من اليسار)
PDF_STOCK_COLUMNS = ("mcap", "ask", "bid", "trades", "val", "vol", "pct", "last", "high", "low", "open")
_NUM_TOKEN = r"-?[\d,]+(?:\.\d+)?"


class Report:
    """نتيجة قراءة التقرير: الأسهم + بيانات وصفية للمطابقة."""

    def __init__(self):
        self.rows: list[dict] = []
        self.date: str | None = None
        self.index: dict = {}          # open, close, high, low, pct, point
        self.totals: dict = {}         # mcap, trades, val, vol (إجمالي السوق كما في التقرير)
        self.breadth: dict = {}        # traded, up, down, flat


def _report_date(text: str) -> str | None:
    m = re.search(r"(20\d\d)-(\d{2})-(\d{2})", text)
    if m:
        return m.group(0)
    m = re.search(r"report of\s*:?\s*(\d{1,2})/(\d{1,2})/(20\d\d)", text, re.I)
    if m:
        d, mo, y = map(int, m.groups())
        return dt.date(y, mo, d).isoformat()
    return None


# ───────────────────────── قراءة الجداول (Excel / CSV) ─────────────────────────
def _sheet_rows(path: Path) -> list[list[list]]:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            raise ValueError("لقراءة ملفات Excel ثبّت المكتبة: pip install openpyxl")
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            return [[list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets]
        finally:
            wb.close()          # تحرير الملف فورًا — وإلا يتعذّر على الموظف استبدال التقرير على ويندوز
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1256", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"تعذّر تحديد ترميز الملف: {path}")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [[row for row in csv.reader(io.StringIO(text), dialect)]]


def _is_data_row(row) -> bool:
    return sum(1 for c in row if to_num(c) is not None) >= 3


def find_header(rows: list[list]):
    """يبحث عن العناوين — قد تمتد على عدة أسطر (عربي/إنجليزي). يعيد (سطر بداية البيانات، {الحقل: العمود})."""
    for i in range(min(len(rows), 40)):
        mapping: dict[str, int] = {}
        end = i
        for k in range(i, min(i + 4, len(rows))):
            if k > i and _is_data_row(rows[k]):
                break
            hits = 0
            for j, cell in enumerate(rows[k]):
                field = _ALIAS_LOOKUP.get(norm_header(cell))
                if field:
                    hits += 1
                    if field not in mapping and j not in mapping.values():
                        mapping[field] = j
            if k > i and hits == 0:      # سطر بلا عناوين (مثل عنوان القطاع) ← انتهت العناوين
                break
            end = k
        if ("sym" in mapping or "name" in mapping or "en" in mapping) and "last" in mapping:
            return end + 1, mapping
    return None, {}


def _row_text(row) -> str:
    return " ".join(clean(c) for c in row if c not in (None, ""))


def _parse_table(rows: list[list], rep: Report) -> bool:
    start, mapping = find_header(rows)
    if start is None:
        return False
    sector = None
    for row in rows[start:]:
        get = lambda f: row[mapping[f]] if f in mapping and mapping[f] < len(row) else None
        text = _row_text(row)
        low = _unify(text)
        if "اجمالي السوق" in low or "market total" in low:
            rep.totals = {f: to_num(get(f)) for f in ("mcap", "trades", "val", "vol") if f in mapping}
            continue
        if "اجمالي" in low or "total" in low:
            continue
        last = to_num(get("last"))
        if last is None:
            if "قطاع" in text or "sector" in low:      # سطر عنوان القطاع
                ar = " ".join(w for w in text.split() if _ARABIC.search(w))
                sector = re.sub(r"^قطاع\s*", "", ar).strip() or sector
            continue
        rec = {"sym": clean(get("sym") or "").upper() or None}
        for f in ("name", "en", "sector"):
            v = clean(get(f) or "")
            if v:
                rec[f] = v
        if sector and "sector" not in rec:
            rec["sector"] = sector
        for f in NUMERIC:
            if f in mapping:
                rec[f] = to_num(get(f))
        if rec["sym"] and not re.fullmatch(r"[A-Z0-9.\-]{1,12}", rec["sym"]):
            rec["sym"] = None
        if rec["sym"] or rec.get("name") or rec.get("en"):
            rep.rows.append(rec)
    _parse_table_footer(rows, rep)
    return bool(rep.rows)


def _parse_table_footer(rows: list[list], rep: Report) -> None:
    """المؤشر وعدد الشركات المرتفعة/المنخفضة أسفل جدول التقرير."""
    want = {"open": ("الفتح", "open"), "close": ("الاغلاق", "close"), "high": ("اعلي", "high"),
            "low": ("ادني", "low"), "pct": ("%",), "point": ("نقاط", "point", "نقاطpoint", "point/نقاط")}
    for i, row in enumerate(rows):
        cols = {}
        for k in range(i, min(i + 3, len(rows))):
            for j, cell in enumerate(rows[k]):
                h = norm_header(cell)
                for f, keys in want.items():
                    if f not in cols and h in keys:
                        cols[f] = j
        if {"open", "close", "high", "low"} <= cols.keys():
            for k in range(i + 1, min(i + 6, len(rows))):
                vals = {f: to_num(rows[k][j]) if j < len(rows[k]) else None for f, j in cols.items()}
                if vals["close"] and vals["open"]:
                    rep.index = {f: v for f, v in vals.items() if v is not None}
                    break
            if rep.index:
                break
    keys = {"traded": ("trades symbols", "المتداوله"), "up": ("advanced", "المرتفعه"),
            "down": ("declin", "المنخفضه"), "flat": ("unchanged", "الثابته")}
    for row in rows:
        for j0, cell in enumerate(row):
            low = _unify(cell)
            for f, ks in keys.items():
                if f in rep.breadth or not any(k in low for k in ks) or not ("عدد" in low or "no" in low):
                    continue
                # العدد هو أقرب خانة رقمية صحيحة إلى خانة العنوان (السطر قد يحوي أرقام المؤشر أيضًا)
                cands = [(abs(j - j0), to_num(c)) for j, c in enumerate(row)
                         if j != j0 and to_num(c) is not None and float(to_num(c)).is_integer()]
                if cands:
                    rep.breadth[f] = int(min(cands)[1])


# ───────────────────────── قراءة نسخة PDF ─────────────────────────
def _pdf_lines(path: Path) -> list[str]:
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        return [clean(l) for l in text.splitlines()]
    except ImportError:
        pass
    exe = shutil.which("pdftotext")
    if not exe:
        raise ValueError("لقراءة ملفات PDF ثبّت المكتبة: pip install pdfplumber")
    out = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), "-"],
                         capture_output=True, check=True).stdout.decode("utf-8", "replace")
    return [clean(l) for l in out.splitlines()]


def _visual_fix(ar: str) -> str:
    """بعض أدوات استخراج PDF تعيد العربية بالترتيب البصري (معكوسة) — نعيدها للترتيب المنطقي."""
    return ar[::-1] if ar else ar


def _parse_pdf(path: Path, rep: Report) -> bool:
    lines = _pdf_lines(path)
    text = "\n".join(lines)
    rep.date = _report_date(text)
    stock_re = re.compile(r"^\s*((?:%s\s+){11})(?:دينار ليبي|يبيل رانيد|LYD|L\.?D)\s+(.*)$" % _NUM_TOKEN)
    sector = None
    after_total = False
    for ln in lines:
        low = _unify(ln)
        if re.search(r"market total", ln, re.I):
            nums = re.findall(_NUM_TOKEN, ln)
            if len(nums) >= 4:
                rep.totals = dict(zip(("mcap", "trades", "val", "vol"), map(to_num, nums[:4])))
            after_total = True
            continue
        if "sector" in low and "total" not in low and not re.match(r"^\s*" + _NUM_TOKEN, ln):
            ar = " ".join(w for w in ln.split() if _ARABIC.search(w))
            if ar:
                cand = [ar, " ".join(_visual_fix(w) for w in reversed(ar.split()))]
                cand = [c for c in cand if c.startswith("قطاع")] or cand
                sector = re.sub(r"^قطاع\s*", "", cand[0]).strip()
            continue
        m = stock_re.match(ln)
        if m:
            nums = [to_num(t) for t in m.group(1).split()]
            rec = dict(zip(PDF_STOCK_COLUMNS, nums))
            tail = m.group(2).strip()
            mm = re.match(r"^([A-Za-z0-9&.,'()\- ]+?)\s+([\u0600-\u06FF].*)$", tail)
            if mm:
                rec["en"], ar = mm.group(1).strip(), mm.group(2).strip()
            else:
                rec["en"], ar = (tail, "") if not _ARABIC.search(tail) else ("", tail)
            # الاسم العربي بالترتيبين (منطقي/معكوس) — المطابقة تختار الصحيح
            rec["name_candidates"] = [ar, " ".join(_visual_fix(w) for w in reversed(ar.split()))]
            rec["name"] = rec["name_candidates"][0]
            rec["sym"] = None
            if sector:
                rec["sector"] = sector
            rep.rows.append(rec)
            continue
        if after_total and not rep.index:
            nums = re.findall(_NUM_TOKEN, ln)
            only_nums = re.fullmatch(r"\s*(?:%s\s*){6}" % _NUM_TOKEN, ln)
            if only_nums and len(nums) == 6:
                low_, high_, pct_, pt_, close_, open_ = map(to_num, nums)
                rep.index = {"low": low_, "high": high_, "pct": pct_, "point": pt_, "close": close_, "open": open_}
    for f, pat in (("traded", r"(\d+)\s+No, ?of Trades"), ("up", r"(\d+)\s+No, ?of Advanced"),
                   ("down", r"(\d+)\s+No, ?of Declin"), ("flat", r"(\d+)\s+No, ?of Unchanged")):
        m = re.search(pat, text, re.I)
        if m:
            rep.breadth[f] = int(m.group(1))
    return bool(rep.rows)


def parse_report(path: Path) -> Report:
    rep = Report()
    if path.suffix.lower() == ".pdf":
        ok = _parse_pdf(path, rep)
    elif path.suffix.lower() in (".xlsx", ".xlsm", ".csv", ".txt"):
        ok = False
        for rows in _sheet_rows(path):
            r = Report()
            if _parse_table(rows, r) and len(r.rows) > len(rep.rows):
                rep = r
                rep.date = _report_date("\n".join(_row_text(x) for x in rows[:12]))
                ok = True
    else:
        raise ValueError(f"صيغة غير مدعومة: {path.suffix} (المدعوم: pdf, xlsx, csv)")
    if not ok:
        raise ValueError("لم أجد جدول الأسهم في التقرير (يجب أن يحتوي اسم الشركة أو رمزها وسعر الإغلاق)")
    if not rep.date:
        rep.date = _report_date(path.stem)
    return rep


# ───────────────────────── مطابقة الشركات ─────────────────────────
class Directory:
    def __init__(self, companies: list[dict]):
        self.by_sym = {c["sym"].upper(): c for c in companies if c.get("sym")}
        self.keys: dict[str, str] = {}
        for c in companies:
            sym = c.get("sym", "").upper()
            for n in [c.get("name"), c.get("en"), *c.get("aliases", [])]:
                if n:
                    k = norm_name(n)
                    self.keys.setdefault(k, sym)
                    self.keys.setdefault(norm_name(strip_al(_unify(n))), sym)

    def resolve(self, rec: dict) -> str | None:
        if rec.get("sym") and rec["sym"] in self.by_sym:
            return rec["sym"]
        cands = [rec.get("en")] + rec.get("name_candidates", [rec.get("name")])
        for n in cands:
            if not n:
                continue
            for k in (norm_name(n), norm_name(strip_al(_unify(n)))):
                if k in self.keys:
                    return self.keys[k]
        return rec.get("sym")


def _temp_sym(rec: dict, taken: set) -> str:
    words = re.findall(r"[A-Za-z]+", rec.get("en") or "")
    base = "".join(w[0] for w in words if w.lower() not in ("of", "and", "the")).upper()[:4] or "NEW"
    sym, i = base, 2
    while sym in taken:
        sym, i = f"{base}{i}", i + 1
    return sym


# ───────────────────────── بناء ملف الجلسة ─────────────────────────
def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise ValueError(f"ملف JSON غير صالح: {path}: {e}") from e


def _derive_prev(r: dict, last: float | None):
    """الإغلاق السابق: من عمود صريح، وإلا من التغير% (ويُفضَّل سعر الفتح إن طابقه)، وإلا None."""
    if r.get("prev"):
        return r["prev"]
    pct, opn = r.get("pct"), r.get("open")
    if last and pct is not None and pct > -100:
        cand = last / (1 + pct / 100.0)
        if opn and abs(opn - cand) <= max(0.006, cand * 0.0006):
            return opn
        return round(cand, 3)
    return None


def build_session(report: Report | list, companies: list[dict], previous: dict | None,
                  date: str | None = None, index_value: float | None = None,
                  index_prev: float | None = None, status: str = "auto",
                  source: str | None = None) -> tuple[dict, list[str]]:
    if isinstance(report, list):                       # توافق: قائمة أسهم فقط
        rep = Report()
        rep.rows = report
        report = rep
    date = date or report.date or dt.date.today().isoformat()
    warnings: list[str] = []
    directory = Directory(companies)
    prev_stocks = {s["sym"]: s for s in (previous or {}).get("stocks", [])}
    same_session = bool(previous) and previous.get("session", {}).get("date") == date

    by_sym: dict[str, dict] = {}
    for r in report.rows:
        sym = directory.resolve(r)
        if not sym:
            sym = _temp_sym(r, set(by_sym) | set(directory.by_sym))
            warnings.append(f"شركة غير معرّفة في companies.json: «{r.get('en') or r.get('name')}» — أُعطيت رمزًا مؤقتًا {sym}")
        elif directory.by_sym and sym not in directory.by_sym:
            warnings.append(f"{sym}: غير موجود في الملف المرجعي companies.json")
        if sym in by_sym:
            warnings.append(f"{sym}: مكرر في التقرير — اعتُمد السطر الأول")
            continue
        by_sym[sym] = r

    order = list(directory.by_sym) + [s for s in by_sym if s not in directory.by_sym]
    stocks = []
    for sym in order:
        r, c, p = by_sym.get(sym, {}), directory.by_sym.get(sym, {}), prev_stocks.get(sym, {})
        last = r.get("last")
        prev = _derive_prev(r, last)
        if prev is None:
            prev = p.get("prev") if same_session else p.get("last")
        if prev is None and r.get("open"):
            prev = r["open"]
        if last is None:
            last = prev
        if prev is None and last is None:
            if c:
                warnings.append(f"{sym}: لا يوجد سعر في التقرير ولا في الجلسة السابقة — لم يُعرض")
            continue
        if prev is None:
            prev = last
            warnings.append(f"{sym}: لا يوجد إغلاق سابق — اعتُبر مساويًا لسعر الإغلاق")
        vol = r.get("vol") or 0
        trades = r.get("trades") or 0
        traded = vol > 0 or trades > 0
        val = r.get("val") or 0
        # نسخة PDF تقرّب قيمة التداول لأقرب دينار؛ إذا نُفّذت كل الكمية بسعر واحد فالقيمة الدقيقة = الكمية × السعر
        hi_, lo_ = r.get("high") or 0, r.get("low") or 0
        if vol and hi_ and abs(hi_ - lo_) < 1e-9 and abs(vol * hi_ - val) < 1.0:
            val = vol * hi_
        st = {
            "sym": sym,
            "name": c.get("name") or r.get("name") or p.get("name") or sym,
            "sector": c.get("sector") or r.get("sector") or p.get("sector") or "أخرى",
            "prev": round(prev, 3),
            "open": round(r.get("open") or (prev if not traded else 0), 3),
            "high": round(r.get("high") or 0, 3),
            "low": round(r.get("low") or 0, 3),
            "last": round(last, 3),
            "vol": int(round(vol)),
            "val": round(val, 3),
            "trades": int(round(trades)),
        }
        for f in ("bid", "ask"):
            if r.get(f):
                st[f] = round(r[f], 3)

        # عدد الأسهم: من القيمة السوقية في التقرير إن أمكن، ويُقارن بالملف المرجعي
        shares = r.get("shares")
        if not shares and r.get("mcap") and last:
            est = r["mcap"] / last
            if abs(round(est) * last - r["mcap"]) <= max(1.0, r["mcap"] * 1e-6):
                shares = round(est)
            else:
                warnings.append(f"{sym}: القيمة السوقية في التقرير لا تقسم على سعر الإغلاق بعدد أسهم صحيح")
        ref_shares = c.get("shares")
        if shares and ref_shares and int(shares) != int(ref_shares):
            warnings.append(f"{sym}: عدد الأسهم في التقرير {int(shares):,} يختلف عن الملف المرجعي {int(ref_shares):,} "
                            f"(زيادة رأس مال؟) — اعتُمد رقم التقرير")
        shares = shares or ref_shares or p.get("shares")
        if shares:
            st["shares"] = int(round(shares))

        # مطابقة التغير% المحسوب مع التقرير
        if r.get("pct") is not None and st["prev"]:
            mine = (st["last"] / st["prev"] - 1) * 100
            if abs(mine - r["pct"]) > 0.0051:
                warnings.append(f"{sym}: التغير المحسوب {mine:.2f}% يختلف عن التقرير {r['pct']:.2f}%")
        stocks.append(st)

    # ── المؤشر ──
    pidx = (previous or {}).get("index", {})
    ri = report.index or {}
    if index_value is None:
        index_value = ri.get("close")
    if index_prev is None:
        index_prev = ri.get("open")
    if index_prev is None:
        index_prev = pidx.get("prev") if same_session else pidx.get("value")
    if index_value is None:
        index_value = pidx.get("value") if same_session else index_prev
    if index_value is None:
        warnings.append("لم تُحدَّد قيمة المؤشر (لا في التقرير ولا عبر --index)")
        index_value = index_prev = 0
    if ri.get("point") is not None and ri.get("close") and ri.get("open"):
        if abs((ri["close"] - ri["open"]) - ri["point"]) > 0.011:
            warnings.append("المؤشر: (الإغلاق − الفتح) لا يساوي التغير بالنقاط في التقرير")
    series = list(pidx.get("series", [])) if same_session else []
    if not series and index_prev:
        series = [index_prev]
    if not series or abs(series[-1] - index_value) > 1e-9:
        series.append(index_value)
    series = series[-400:]
    index = {"value": round(index_value, 2), "prev": round(index_prev or 0, 2),
             "series": [round(x, 2) for x in series]}
    for f in ("high", "low"):
        if ri.get(f):
            index[f] = round(ri[f], 2)

    session = {
        "demo": False,
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "source": source or "",
        "session": {
            "date": date,
            "openT": (previous or {}).get("session", {}).get("openT", "10:00"),
            "closeT": (previous or {}).get("session", {}).get("closeT", "13:00"),
            "status": status,
        },
        "index": index,
        "stocks": stocks,
    }
    missing = [s["sym"] for s in stocks if not s.get("shares")]
    if missing:
        warnings.append("بلا عدد أسهم (لن تُحسب قيمتها السوقية): " + ", ".join(missing))
    warnings += sanity_checks(stocks)
    warnings += reconcile(stocks, report)
    return session, warnings


def reconcile(stocks: list[dict], report: Report) -> list[str]:
    """مطابقة ما ستعرضه الشاشة مع إجماليات التقرير نفسه — أي فرق يعني خطأ قراءة أو خطأ في التقرير."""
    w = []
    t = report.totals or {}
    mine = {"val": sum(s["val"] for s in stocks), "vol": sum(s["vol"] for s in stocks),
            "trades": sum(s["trades"] for s in stocks),
            "mcap": sum(s["last"] * s.get("shares", 0) for s in stocks)}
    labels = {"val": "قيمة التداول", "vol": "كمية التداول", "trades": "عدد العمليات", "mcap": "القيمة السوقية"}
    for f, v in t.items():
        if v is None:
            continue
        tol = max(0.01, abs(v) * 1e-6)
        if abs(mine[f] - v) > tol:
            w.append(f"مطابقة: {labels[f]} المحسوبة {mine[f]:,.3f} ≠ إجمالي التقرير {v:,.3f}")
    b = report.breadth or {}
    traded = [s for s in stocks if s["vol"] > 0 or s["trades"] > 0]
    calc = {"traded": len(traded),
            "up": sum(1 for s in traded if s["last"] > s["prev"] + 1e-6),
            "down": sum(1 for s in traded if s["last"] < s["prev"] - 1e-6)}
    calc["flat"] = calc["traded"] - calc["up"] - calc["down"]
    names = {"traded": "المتداولة", "up": "المرتفعة", "down": "المنخفضة", "flat": "الثابتة"}
    for f, v in b.items():
        if calc.get(f) != v:
            w.append(f"مطابقة: عدد الشركات {names[f]} المحسوب {calc.get(f)} ≠ التقرير {v}")
    return w


def sanity_checks(stocks: list[dict]) -> list[str]:
    w = []
    for s in stocks:
        if s["vol"] > 0:
            unchanged_close = abs(s["last"] - s["prev"]) < 1e-6
            # سعر إغلاق لم يتغير رغم تداول بسعر آخر: التداول لم يستوفِ شرط تغيير سعر الإغلاق — ليس خطأ
            if (s["high"] and s["low"] and not unchanged_close
                    and not (s["low"] - 1e-6 <= s["last"] <= s["high"] + 1e-6)):
                w.append(f"{s['sym']}: سعر الإغلاق {s['last']} خارج نطاق التنفيذ {s['low']}–{s['high']}")
            if s["val"] and s["high"] and s["low"]:
                vw = s["val"] / s["vol"]
                if not (s["low"] * 0.995 <= vw <= s["high"] * 1.005):
                    w.append(f"{s['sym']}: متوسط التنفيذ {vw:.3f} خارج النطاق")
        if s["prev"] and abs(s["last"] / s["prev"] - 1) > 0.10:
            w.append(f"{s['sym']}: تغير يتجاوز 10% — يُرجى التحقق")
        if s.get("bid") and s.get("ask") and s["bid"] > s["ask"] + 1e-6:
            w.append(f"{s['sym']}: أفضل طلب {s['bid']} أعلى من أفضل عرض {s['ask']}")
    return w


def write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):                       # على ويندوز قد يكون الملف مفتوحًا للقراءة لحظيًا
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.2 * (attempt + 1))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def convert(report_path: Path, args) -> int:
    out = Path(args.out)
    companies = load_json(Path(args.companies), {}).get("companies", [])
    previous = load_json(out, None)
    report = parse_report(report_path)
    session, warnings = build_session(report, companies, previous, args.date,
                                      args.index, args.index_prev, args.status,
                                      source=report_path.name)
    for w in warnings:
        print("  تحذير:", w, file=sys.stderr)
    if args.dry_run:
        print(json.dumps(session, ensure_ascii=False, indent=2))
    else:
        write_atomic(out, session)
    traded = sum(1 for s in session["stocks"] if s["vol"] > 0)
    ok = "دون فروق" if not any(w.startswith("مطابقة") for w in warnings) else "مع فروق — راجع التحذيرات"
    print(f"✔ {report_path.name}: جلسة {session['session']['date']} — "
          f"{len(session['stocks'])} شركة ({traded} متداولة)، المؤشر {session['index']['value']:,.2f} — "
          f"المطابقة مع إجماليات التقرير {ok} → {out if not args.dry_run else '(عرض فقط)'}")
    return 0


def latest_report(folder: Path) -> Path | None:
    files = [p for p in folder.iterdir()
             if p.suffix.lower() in (".xlsx", ".xlsm", ".csv", ".pdf") and not p.name.startswith(("~$", "."))]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def watch(folder: Path, args) -> None:
    print(f"مراقبة المجلد {folder} كل {args.interval} ثانية — Ctrl+C للإيقاف")
    seen = None
    while True:
        try:
            p = latest_report(folder)
            if p:
                sig = (p, p.stat().st_mtime, p.stat().st_size)
                if sig != seen:
                    time.sleep(1.0)                    # انتظار اكتمال حفظ الملف
                    if (p.stat().st_mtime, p.stat().st_size) == sig[1:]:
                        convert(p, args)
                        seen = sig
        except (ValueError, OSError) as e:
            print("  خطأ:", e, file=sys.stderr)       # يستمر في المراقبة
        time.sleep(args.interval)


def _utf8_console() -> None:
    """طرفية ويندوز تستخدم ترميزًا محليًا (cp1252/cp720) يعجز عن العربية ورموز مثل ✔ — نفرض UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _utf8_console()
    ap = argparse.ArgumentParser(description="تحويل تقرير عمليات التداول اليومي إلى ملف شاشة العرض")
    ap.add_argument("report", nargs="?", help="ملف التقرير (pdf أو xlsx أو csv)")
    ap.add_argument("--watch", metavar="DIR", help="مراقبة مجلد وتحويل أحدث تقرير فيه آليًا")
    ap.add_argument("--interval", type=int, default=30, help="فترة المراقبة بالثواني (افتراضي 30)")
    ap.add_argument("--out", default=str(DEFAULT_DATA_DIR / "session.json"), help="ملف الإخراج")
    ap.add_argument("--companies", default=str(DEFAULT_DATA_DIR / "companies.json"), help="الملف المرجعي للشركات")
    ap.add_argument("--date", help="تاريخ الجلسة YYYY-MM-DD (افتراضيًا من التقرير، وإلا اليوم)")
    ap.add_argument("--index", type=float, help="قيمة المؤشر (افتراضيًا من التقرير)")
    ap.add_argument("--index-prev", type=float, help="إغلاق المؤشر السابق (افتراضيًا من التقرير)")
    ap.add_argument("--status", default="auto", choices=["auto", "open", "closed"], help="حالة الجلسة")
    ap.add_argument("--dry-run", action="store_true", help="عرض الناتج دون كتابة الملف")
    args = ap.parse_args(argv)

    if args.watch:
        watch(Path(args.watch), args)
        return 0
    if not args.report:
        ap.error("حدد ملف التقرير أو --watch")
    try:
        return convert(Path(args.report), args)
    except ValueError as e:
        print("خطأ:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
