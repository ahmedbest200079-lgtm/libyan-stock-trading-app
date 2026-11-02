#!/usr/bin/env python3
"""
منظومة التغذية — تحويل تقرير التداول اليومي (Excel / CSV) إلى ملف شاشة العرض data/session.json

الاستخدام:
  # تحويل ملف واحد
  python lsm_feeder.py report.xlsx --index 1134.57 --index-prev 1139.04

  # مراقبة مجلد: كلما وُضع/عُدّل تقرير فيه يُحوَّل آليًا (للتشغيل الدائم أثناء الجلسة)
  python lsm_feeder.py --watch "D:\\LSM\\reports" --interval 30

المبادئ:
  - يتعرف على أعمدة التقرير بأسمائها العربية أو الإنجليزية (انظر COLUMN_ALIASES)، ويمكن إضافة أسماء أخرى بسهولة.
  - يدمج الملف المرجعي data/companies.json (الاسم، القطاع، عدد الأسهم) فتظهر كل الشركات المدرجة
    حتى غير المتداولة، وتُحسب القيمة السوقية على الشاشة.
  - إذا غاب سعر الإغلاق السابق يُؤخذ من آخر سعر في ملف الجلسة السابق (ترحيل تلقائي).
  - مسار المؤشر: تُضاف كل قيمة جديدة إلى سلسلة اليوم، وتبدأ سلسلة جديدة مع جلسة جديدة.
  - الكتابة ذرّية (ملف مؤقت ثم استبدال) فلا تقرأ الشاشة ملفًا ناقصًا أبدًا.
  - لا يحتاج سوى بايثون 3.8+؛ ومكتبة openpyxl فقط لملفات Excel (pip install openpyxl).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = HERE.parent / "data"

# أسماء الأعمدة المقبولة لكل حقل (تُطابَق بعد التطبيع: حذف المسافات والتشكيل وتوحيد الهمزات)
COLUMN_ALIASES: dict[str, list[str]] = {
    "sym":    ["الرمز", "رمز السهم", "رمز الشركة", "sym", "symbol", "ticker", "code"],
    "name":   ["الشركة", "اسم الشركة", "اسم السهم", "name", "company"],
    "sector": ["القطاع", "sector"],
    "prev":   ["إغلاق سابق", "الإغلاق السابق", "سعر الإغلاق السابق", "السعر المرجعي", "prev", "previous close", "prev close", "reference price"],
    "open":   ["الافتتاح", "سعر الافتتاح", "open", "open price"],
    "high":   ["الأعلى", "أعلى سعر", "high"],
    "low":    ["الأدنى", "أدنى سعر", "low"],
    "last":   ["آخر سعر", "سعر الإغلاق", "الإغلاق", "last", "close", "close price", "last price"],
    "vol":    ["الكمية", "الكمية المتداولة", "حجم التداول", "عدد الأسهم المتداولة", "vol", "volume", "quantity", "qty"],
    "val":    ["القيمة", "قيمة التداول", "القيمة المتداولة", "القيمة (د.ل)", "val", "value", "turnover"],
    "trades": ["الصفقات", "عدد الصفقات", "trades", "deals", "no. of trades", "transactions"],
    "shares": ["عدد الأسهم المصدرة", "الأسهم المصدرة", "عدد الأسهم", "shares", "shares outstanding", "issued shares"],
}
NUMERIC = ("prev", "open", "high", "low", "last", "vol", "val", "trades", "shares")

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
_TASHKEEL = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u0640]")


def norm_header(s: str) -> str:
    s = _TASHKEEL.sub("", str(s or "")).strip().lower()
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"[\s_\-:()\.]+", "", s)


_ALIAS_LOOKUP = {norm_header(a): field for field, names in COLUMN_ALIASES.items() for a in names}


def to_num(v):
    """يحوّل '1,250.5' أو '١٬٢٥٠٫٥' أو '(12.5)' أو '-' إلى رقم؛ يعيد None للخانة الفارغة."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).translate(_AR_DIGITS).strip().replace("\u066a", "%")
    if s in ("", "-", "—", "–", "N/A", "n/a"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d.\-eE]", "", s.replace(",", ""))
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


# ───────────────────────── قراءة التقرير ─────────────────────────
def read_rows(path: Path) -> list[list]:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            sys.exit("لقراءة ملفات Excel ثبّت المكتبة: pip install openpyxl")
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        best = []
        for ws in wb.worksheets:                     # الورقة التي تحوي جدول الأسهم
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            if find_header(rows)[0] is not None and len(rows) > len(best):
                best = rows
        return best
    if ext in (".csv", ".txt"):
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "cp1256", "utf-16"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            sys.exit(f"تعذّر تحديد ترميز الملف: {path}")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
        return [row for row in csv.reader(io.StringIO(text), dialect)]
    sys.exit(f"صيغة غير مدعومة: {ext} (المدعوم: xlsx, csv)")


def find_header(rows: list[list]):
    """يبحث في أول 30 سطرًا عن سطر العناوين (يحتوي الرمز + آخر سعر على الأقل)."""
    for i, row in enumerate(rows[:30]):
        mapping = {}
        for j, cell in enumerate(row):
            field = _ALIAS_LOOKUP.get(norm_header(cell))
            if field and field not in mapping:
                mapping[field] = j
        if "sym" in mapping and ("last" in mapping or "prev" in mapping):
            return i, mapping
    return None, {}


def parse_report(path: Path) -> list[dict]:
    rows = read_rows(path)
    hi, mapping = find_header(rows)
    if hi is None:
        raise ValueError("لم أجد سطر العناوين في التقرير (يجب أن يحتوي عمود الرمز وعمود آخر سعر/سعر الإغلاق)")
    out = []
    for row in rows[hi + 1:]:
        get = lambda f: row[mapping[f]] if f in mapping and mapping[f] < len(row) else None
        sym = str(get("sym") or "").strip().upper()
        if not sym or not re.match(r"^[A-Z0-9.\-]{1,12}$", sym):
            continue                                  # سطور الإجمالي/الملاحظات
        rec = {"sym": sym}
        for f in ("name", "sector"):
            v = get(f)
            if v not in (None, ""):
                rec[f] = str(v).strip()
        for f in NUMERIC:
            if f in mapping:
                rec[f] = to_num(get(f))
        out.append(rec)
    if not out:
        raise ValueError("لم أجد أي سهم في التقرير")
    return out


# ───────────────────────── الدمج وبناء ملف الجلسة ─────────────────────────
def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise ValueError(f"ملف JSON غير صالح: {path}: {e}") from e


def build_session(report: list[dict], companies: list[dict], previous: dict | None,
                  date: str, index_value: float | None, index_prev: float | None,
                  status: str = "auto") -> tuple[dict, list[str]]:
    warnings: list[str] = []
    ref = {c["sym"].upper(): c for c in companies if c.get("sym")}
    prev_stocks = {s["sym"]: s for s in (previous or {}).get("stocks", [])}
    same_session = bool(previous) and previous.get("session", {}).get("date") == date
    by_sym = {r["sym"]: r for r in report}

    for sym in by_sym:
        if ref and sym not in ref:
            warnings.append(f"{sym}: غير موجود في الملف المرجعي companies.json")

    order = list(ref) + [s for s in by_sym if s not in ref]
    stocks = []
    for sym in order:
        r, c, p = by_sym.get(sym, {}), ref.get(sym, {}), prev_stocks.get(sym, {})
        # الإغلاق السابق: من التقرير، وإلا من ملف الجلسة السابقة (آخر سعرها إن كانت جلسة أخرى)
        prev = r.get("prev")
        if prev is None:
            prev = p.get("prev") if same_session else p.get("last")
        last = r.get("last")
        if last is None:
            last = prev
        if prev is None and last is None:
            warnings.append(f"{sym}: لا يوجد سعر — حُذف من الشاشة")
            continue
        if prev is None:
            prev = last
            warnings.append(f"{sym}: لا يوجد إغلاق سابق — اعتُبر مساويًا لآخر سعر")
        vol = r.get("vol") or 0
        traded = vol > 0 or (r.get("trades") or 0) > 0
        st = {
            "sym": sym,
            "name": r.get("name") or c.get("name") or p.get("name") or sym,
            "sector": c.get("sector") or r.get("sector") or p.get("sector") or "أخرى",
            "prev": round(prev, 3),
            "open": round(r.get("open") or (prev if not traded else 0), 3),
            "high": round(r.get("high") or 0, 3),
            "low": round(r.get("low") or 0, 3),
            "last": round(last, 3),
            "vol": int(round(vol)),
            "val": round(r.get("val") or 0, 3),
            "trades": int(round(r.get("trades") or 0)),
        }
        shares = r.get("shares") or c.get("shares") or p.get("shares")
        if shares:
            st["shares"] = int(round(shares))
        stocks.append(st)

    # مسار المؤشر
    pidx = (previous or {}).get("index", {})
    if index_prev is None:
        index_prev = pidx.get("prev") if same_session else pidx.get("value")
    if index_value is None:
        index_value = pidx.get("value") if same_session else index_prev
    if index_value is None:
        warnings.append("لم تُحدَّد قيمة المؤشر (--index)")
        index_value = index_prev = 0
    series = list(pidx.get("series", [])) if same_session else []
    if not series and index_prev:
        series = [index_prev]
    if not series or abs(series[-1] - index_value) > 1e-9:
        series.append(index_value)
    series = series[-400:]

    session = {
        "demo": False,
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "session": {
            "date": date,
            "openT": (previous or {}).get("session", {}).get("openT", "10:00"),
            "closeT": (previous or {}).get("session", {}).get("closeT", "13:00"),
            "status": status,
        },
        "index": {"value": round(index_value, 2), "prev": round(index_prev or 0, 2),
                  "series": [round(x, 2) for x in series]},
        "stocks": stocks,
    }
    missing_shares = [s["sym"] for s in stocks if not s.get("shares")]
    if missing_shares:
        warnings.append("بلا عدد أسهم (لن تُحسب قيمتها السوقية): " + ", ".join(missing_shares))
    warnings += sanity_checks(stocks)
    return session, warnings


def sanity_checks(stocks: list[dict]) -> list[str]:
    w = []
    for s in stocks:
        if s["vol"] > 0:
            if s["high"] and s["low"] and not (s["low"] - 1e-6 <= s["last"] <= s["high"] + 1e-6):
                w.append(f"{s['sym']}: آخر سعر {s['last']} خارج نطاق التنفيذ {s['low']}–{s['high']}")
            if s["val"] and s["high"] and s["low"]:
                vw = s["val"] / s["vol"]
                if not (s["low"] * 0.995 <= vw <= s["high"] * 1.005):
                    w.append(f"{s['sym']}: متوسط التنفيذ {vw:.3f} خارج النطاق")
        if s["prev"] and abs(s["last"] / s["prev"] - 1) > 0.10:
            w.append(f"{s['sym']}: تغير يتجاوز 10% — يُرجى التحقق")
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
                                      args.index, args.index_prev, args.status)
    for w in warnings:
        print("  تحذير:", w, file=sys.stderr)
    if args.dry_run:
        print(json.dumps(session, ensure_ascii=False, indent=2))
    else:
        write_atomic(out, session)
    traded = sum(1 for s in session["stocks"] if s["vol"] > 0)
    print(f"✔ {report_path.name}: {len(session['stocks'])} شركة ({traded} متداولة) → {out}")
    return 0


def latest_report(folder: Path) -> Path | None:
    files = [p for p in folder.iterdir()
             if p.suffix.lower() in (".xlsx", ".xlsm", ".csv") and not p.name.startswith(("~$", "."))]
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="تحويل تقرير التداول اليومي إلى ملف شاشة العرض")
    ap.add_argument("report", nargs="?", help="ملف التقرير (xlsx أو csv)")
    ap.add_argument("--watch", metavar="DIR", help="مراقبة مجلد وتحويل أحدث تقرير فيه آليًا")
    ap.add_argument("--interval", type=int, default=30, help="فترة المراقبة بالثواني (افتراضي 30)")
    ap.add_argument("--out", default=str(DEFAULT_DATA_DIR / "session.json"), help="ملف الإخراج")
    ap.add_argument("--companies", default=str(DEFAULT_DATA_DIR / "companies.json"), help="الملف المرجعي للشركات")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="تاريخ الجلسة YYYY-MM-DD (افتراضي اليوم)")
    ap.add_argument("--index", type=float, help="قيمة المؤشر العام الحالية")
    ap.add_argument("--index-prev", type=float, help="إغلاق المؤشر السابق")
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
