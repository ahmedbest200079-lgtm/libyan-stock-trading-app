#!/usr/bin/env python3
"""
وحدة الربط بقاعدة بيانات نظام التداول — تغذية شاشة العرض آليًا دون أي تدخل بشري

تقرأ الأسعار مباشرة من قاعدة البيانات (بحساب للقراءة فقط) كل بضع ثوانٍ أثناء الجلسة، وتمرّرها
على نفس منطق المطابقة والتحقق المستخدم مع التقارير (lsm_feeder.build_session)، ثم تكتب
data/session.json كتابة ذرّية فتتحدث الشاشة.

  python lsm_db_feeder.py --config db_feeder.ini            # التشغيل الدائم (خدمة)
  python lsm_db_feeder.py --config db_feeder.ini --test     # اختبار الاتصال وعرض الأعمدة والنتيجة دون كتابة
  python lsm_db_feeder.py --config db_feeder.ini --once     # لقطة واحدة ثم خروج (يتجاهل الجدول الزمني)
  python lsm_db_feeder.py --make-demo-db demo.sqlite        # قاعدة تجريبية للتدريب قبل توفر القاعدة الحقيقية

قواعد البيانات المدعومة (يُثبَّت مشغّل النوع المستخدم فقط):
  sqlserver / odbc  → pip install pyodbc        (+ Microsoft ODBC Driver 17/18 for SQL Server)
  oracle            → pip install oracledb      (الوضع الرقيق — لا يحتاج Oracle Client)
  postgresql        → pip install "psycopg[binary]"
  mysql / mariadb   → pip install pymysql
  sqlite            → مدمج في بايثون (للتجربة والاختبار)

الضوابط الأمنية المدمجة:
  - لا تُنفَّذ إلا استعلامات SELECT / WITH مفردة؛ يُرفض أي أمر آخر قبل إرساله.
  - تُفتح الجلسة في وضع القراءة فقط حيث يدعمه المشغّل (SQL Server / PostgreSQL / SQLite).
  - كلمة المرور تُقرأ من متغير بيئة (password_env) ولا يلزم كتابتها في الملف.
"""
from __future__ import annotations

import argparse
import configparser
import datetime as dt
import hashlib
import json
import logging
import logging.handlers
import os
import re
import shutil
import smtplib
import sqlite3
import sys
import time
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lsm_feeder as F  # noqa: E402

log = logging.getLogger("lsm_db_feeder")

STOCK_FIELDS = ("sym", "name", "en", "sector", "prev", "open", "high", "low", "last", "pct",
                "vol", "val", "trades", "bid", "ask", "mcap", "shares")
INDEX_FIELDS = ("value", "prev", "high", "low", "date")
_INDEX_ALIASES = {
    "value": ["index_value", "index", "value", "close", "index_close", "قيمة المؤشر", "المؤشر"],
    "prev":  ["index_prev", "prev", "prev_close", "previous_close", "open", "index_open", "الإغلاق السابق"],
    "high":  ["index_high", "high", "الأعلى"],
    "low":   ["index_low", "low", "الأدنى"],
    "date":  ["session_date", "trade_date", "date", "تاريخ الجلسة"],
}
DAY_NAMES = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}


# ───────────────────────── الإعدادات ─────────────────────────
class Config:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.base = self.path.parent
        cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), interpolation=None)
        cp.optionxform = str
        with open(self.path, encoding="utf-8-sig") as f:
            cp.read_file(f)
        self.cp = cp

    def get(self, section, key, default=""):
        v = self.cp.get(section, key, fallback=default)
        return v.strip() if isinstance(v, str) else v

    def getint(self, section, key, default):
        v = self.get(section, key, "")
        return int(v) if v else default

    def getbool(self, section, key, default=False):
        v = self.get(section, key, "").lower()
        return default if not v else v in ("1", "true", "yes", "on", "نعم")

    def path_of(self, section, key, default):
        v = self.get(section, key, "") or default
        p = Path(os.path.expandvars(v))
        return p if p.is_absolute() else (self.base / p).resolve()

    def secret(self, section, key):
        env = self.get(section, key + "_env", "")
        if env and os.environ.get(env):
            return os.environ[env]
        return self.get(section, key, "")

    def mapping(self, section, fields) -> dict:
        if not self.cp.has_section(section):
            return {}
        return {f: self.get(section, f) for f in fields if self.get(section, f)}


# ───────────────────────── الاتصال بقاعدة البيانات ─────────────────────────
_SAFE_SQL = re.compile(r"^\s*(select|with)\b", re.I)
_FORBIDDEN = re.compile(r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|exec|execute|call|into)\b", re.I)


def check_readonly_sql(sql: str) -> str:
    """طبقة حماية إضافية: استعلام SELECT واحد فقط، دون أي أمر تعديل."""
    s = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip().rstrip(";").strip()
    if not _SAFE_SQL.match(s) or ";" in s:
        raise ValueError("يُسمح فقط باستعلام SELECT واحد")
    stripped = re.sub(r"'[^']*'", "''", s)                  # تجاهل النصوص بين علامات الاقتباس
    if _FORBIDDEN.search(stripped):
        raise ValueError("الاستعلام يحتوي أمرًا غير مسموح (للقراءة فقط)")
    return s


def connect(cfg: Config):
    t = cfg.get("database", "type", "sqlite").lower()
    timeout = cfg.getint("database", "timeout", 15)
    host, port = cfg.get("database", "host"), cfg.get("database", "port")
    db, user = cfg.get("database", "database"), cfg.get("database", "user")
    pwd = cfg.secret("database", "password")
    extra = cfg.get("database", "extra")

    if t == "sqlite":
        path = cfg.path_of("database", "path", "demo.sqlite")
        if not path.exists():
            raise FileNotFoundError(f"قاعدة SQLite غير موجودة: {path}")
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout)

    if t in ("sqlserver", "mssql", "odbc"):
        import pyodbc
        if t == "odbc":
            cs = f"DSN={cfg.get('database', 'dsn')};"
        else:
            drv = cfg.get("database", "odbc_driver", "ODBC Driver 18 for SQL Server")
            server = f"{host},{port}" if port else host
            cs = f"DRIVER={{{drv}}};SERVER={server};DATABASE={db};ApplicationIntent=ReadOnly;"
        cs += f"UID={user};PWD={pwd};" if user else "Trusted_Connection=yes;"
        if extra:
            cs += extra if extra.endswith(";") else extra + ";"
        conn = pyodbc.connect(cs, timeout=timeout, readonly=True, autocommit=True)
        conn.timeout = timeout
        return conn

    if t == "oracle":
        import oracledb
        dsn = cfg.get("database", "dsn") or f"{host}:{port or 1521}/{cfg.get('database', 'service_name') or db}"
        conn = oracledb.connect(user=user, password=pwd, dsn=dsn, tcp_connect_timeout=timeout)
        conn.call_timeout = timeout * 1000
        return conn

    if t in ("postgresql", "postgres"):
        import psycopg
        return psycopg.connect(host=host, port=port or 5432, dbname=db, user=user, password=pwd,
                               connect_timeout=timeout, autocommit=True,
                               options="-c default_transaction_read_only=on")

    if t in ("mysql", "mariadb"):
        import pymysql
        return pymysql.connect(host=host, port=int(port or 3306), database=db, user=user, password=pwd,
                               connect_timeout=timeout, read_timeout=timeout, autocommit=True)

    raise ValueError(f"نوع قاعدة بيانات غير مدعوم: {t}")


def fetch(conn, sql: str) -> tuple[list[str], list[tuple]]:
    sql = check_readonly_sql(sql)
    cur = conn.cursor()
    try:
        cur.execute(sql)
        cols = [str(d[0]) for d in cur.description]
        return cols, [tuple(r) for r in cur.fetchall()]
    finally:
        try:
            cur.close()
        except Exception:
            pass


# ───────────────────────── تحويل النتائج ─────────────────────────
def resolve_columns(cols: list[str], explicit: dict, aliases: dict | None = None) -> dict:
    """{الحقل: رقم العمود} — من الإعداد صراحة، وإلا بالتعرف الآلي على أسماء الأعمدة."""
    norm = {F.norm_header(c): i for i, c in enumerate(cols)}
    out = {}
    for field, col in explicit.items():
        i = norm.get(F.norm_header(col))
        if i is None:
            raise ValueError(f"العمود «{col}» المحدد للحقل {field} غير موجود في نتيجة الاستعلام: {', '.join(cols)}")
        out[field] = i
    for i, c in enumerate(cols):
        h = F.norm_header(c)
        if aliases is None:
            field = F._ALIAS_LOOKUP.get(h)
        else:
            field = next((f for f, names in aliases.items() if h in {F.norm_header(n) for n in names}), None)
        if field and field not in out and i not in out.values():
            out[field] = i
    return out


def rows_to_records(cols, rows, mapping: dict) -> list[dict]:
    m = resolve_columns(cols, mapping)
    if "sym" not in m and "name" not in m and "en" not in m:
        raise ValueError("نتيجة الاستعلام لا تحتوي عمود رمز الشركة أو اسمها")
    if "last" not in m and "prev" not in m:
        raise ValueError("نتيجة الاستعلام لا تحتوي عمود سعر (آخر سعر / الإغلاق السابق)")
    recs = []
    for r in rows:
        rec = {}
        for f, i in m.items():
            v = r[i]
            if f in ("sym", "name", "en", "sector"):
                v = F.clean(v) if v is not None else ""
                if f == "sym":
                    v = v.upper() or None
                if v:
                    rec[f] = v
            else:
                rec[f] = F.to_num(v)
        rec.setdefault("sym", None)
        if rec.get("sym") or rec.get("name") or rec.get("en"):
            recs.append(rec)
    return recs


def index_from_rows(cols, rows, mapping: dict) -> dict:
    if not rows:
        return {}
    m = resolve_columns(cols, mapping, _INDEX_ALIASES)
    r = rows[0]
    out = {}
    if "value" in m: out["close"] = F.to_num(r[m["value"]])
    if "prev" in m:  out["open"] = F.to_num(r[m["prev"]])
    if "high" in m:  out["high"] = F.to_num(r[m["high"]])
    if "low" in m:   out["low"] = F.to_num(r[m["low"]])
    if "date" in m and r[m["date"]] is not None:
        d = r[m["date"]]
        out["date"] = d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]
    return {k: v for k, v in out.items() if v is not None}


# ───────────────────────── الجدول الزمني والعطلات ─────────────────────────
def _hm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


class Schedule:
    def __init__(self, cfg: Config):
        days = cfg.get("schedule", "days", "sun,mon,tue,wed,thu")
        self.days = {DAY_NAMES[d.strip()[:3].lower()] for d in days.split(",") if d.strip()}
        self.open = _hm(cfg.get("schedule", "open", "10:00"))
        self.close = _hm(cfg.get("schedule", "close", "13:00"))
        self.pre = dt.timedelta(minutes=cfg.getint("schedule", "pre_minutes", 15))
        self.post = dt.timedelta(minutes=cfg.getint("schedule", "post_minutes", 30))
        self.holidays: dict[str, str] = {}
        hf = cfg.path_of("schedule", "holidays_file", "")
        if hf and hf.is_file():
            data = F.load_json(hf, {})
            for h in data.get("holidays", []):
                self.holidays[h["date"]] = h.get("name", "عطلة")

    def holiday(self, d: dt.date) -> str | None:
        return self.holidays.get(d.isoformat())

    def trading_day(self, d: dt.date) -> bool:
        return d.isoweekday() in self.days and not self.holiday(d)

    def window(self, d: dt.date) -> tuple[dt.datetime, dt.datetime]:
        return (dt.datetime.combine(d, self.open) - self.pre, dt.datetime.combine(d, self.close) + self.post)

    def active(self, now: dt.datetime) -> bool:
        if not self.trading_day(now.date()):
            return False
        a, b = self.window(now.date())
        return a <= now <= b

    def in_session(self, now: dt.datetime) -> bool:
        return (self.trading_day(now.date())
                and dt.datetime.combine(now.date(), self.open) <= now < dt.datetime.combine(now.date(), self.close))

    def next_start(self, now: dt.datetime) -> dt.datetime:
        for k in range(0, 30):
            d = now.date() + dt.timedelta(days=k)
            if self.trading_day(d):
                a, _ = self.window(d)
                if a > now:
                    return a
        return now + dt.timedelta(days=1)


# ───────────────────────── التنبيهات ─────────────────────────
class Alerter:
    def __init__(self, cfg: Config):
        self.enabled = cfg.getbool("alerts", "enabled", False)
        self.host = cfg.get("alerts", "smtp_host")
        self.port = cfg.getint("alerts", "smtp_port", 587)
        self.tls = cfg.getbool("alerts", "smtp_tls", True)
        self.user = cfg.get("alerts", "smtp_user")
        self.pwd = cfg.secret("alerts", "smtp_password")
        self.sender = cfg.get("alerts", "from") or self.user
        self.to = [x.strip() for x in cfg.get("alerts", "to").split(",") if x.strip()]
        self.repeat = dt.timedelta(minutes=cfg.getint("alerts", "repeat_minutes", 60))
        self.sent: dict[str, dt.datetime] = {}

    def send(self, key: str, subject: str, body: str, now: dt.datetime | None = None) -> bool:
        now = now or dt.datetime.now()
        last = self.sent.get(key)
        if last and now - last < self.repeat:
            return False                               # منع تكرار التنبيه نفسه
        self.sent[key] = now
        log.warning("تنبيه: %s — %s", subject, body.splitlines()[0] if body else "")
        if not (self.enabled and self.host and self.to):
            return True
        msg = EmailMessage()
        msg["Subject"] = f"[شاشة سوق المال] {subject}"
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.to)
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=20) as s:
                if self.tls:
                    s.starttls()
                if self.user:
                    s.login(self.user, self.pwd)
                s.send_message(msg)
        except Exception as e:                         # فشل البريد لا يوقف التغذية
            log.error("تعذّر إرسال التنبيه بالبريد: %s", e)
        return True

    def clear(self, key: str):
        self.sent.pop(key, None)


# ───────────────────────── المنظومة ─────────────────────────
def _digest(session: dict) -> str:
    d = {k: v for k, v in session.items() if k != "generatedAt"}
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class DbFeeder:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.schedule = Schedule(cfg)
        self.alerter = Alerter(cfg)
        self.out = cfg.path_of("output", "session", "../data/session.json")
        self.companies = cfg.path_of("output", "companies", "../data/companies.json")
        self.archive = cfg.path_of("output", "archive_dir", "../data/archive")
        self.status_file = cfg.path_of("output", "status_file", "../data/feeder_status.json")
        self.interval = cfg.getint("schedule", "interval", 15)
        self.heartbeat = cfg.getint("schedule", "heartbeat_seconds", 60)
        self.idle_check = cfg.getint("schedule", "idle_check_minutes", 10)
        self.stale = dt.timedelta(minutes=cfg.getint("alerts", "stale_minutes", 5))
        self.stock_sql = cfg.get("queries", "stocks")
        self.index_sql = cfg.get("queries", "index")
        self.colmap = cfg.mapping("columns", STOCK_FIELDS)
        self.idxmap = cfg.mapping("index_columns", INDEX_FIELDS)
        self.conn = None
        self.last_digest = None
        self.last_write = None
        self.last_ok = None
        self.fail_since = None
        self.archived_for = None
        self.reconcile_alerted_for = None
        if not self.stock_sql:
            raise ValueError("لم يُحدَّد استعلام الأسهم [queries] stocks في ملف الإعداد")

    # ── لقطة واحدة ──
    def snapshot(self, now: dt.datetime | None = None) -> tuple[dict, list[str], int]:
        now = now or dt.datetime.now()
        if self.conn is None:
            self.conn = connect(self.cfg)
            log.info("تم الاتصال بقاعدة البيانات (%s)", self.cfg.get("database", "type"))
        cols, rows = fetch(self.conn, self.stock_sql)
        rep = F.Report()
        rep.rows = rows_to_records(cols, rows, self.colmap)
        if self.index_sql:
            icols, irows = fetch(self.conn, self.index_sql)
            rep.index = index_from_rows(icols, irows, self.idxmap)
        date = rep.index.pop("date", None) or now.date().isoformat()
        companies = F.load_json(self.companies, {}).get("companies", [])
        previous = F.load_json(self.out, None)
        session, warnings = F.build_session(rep, companies, previous, date, None, None,
                                            "auto", source="قاعدة بيانات نظام التداول")
        session["session"]["openT"] = self.schedule.open.strftime("%H:%M")
        session["session"]["closeT"] = self.schedule.close.strftime("%H:%M")
        return session, warnings, len(rows)

    def write_if_needed(self, session: dict, now: dt.datetime) -> bool:
        """يكتب عند تغيّر البيانات، أو كل heartbeat ثانية حتى لا تظن الشاشة أن التغذية توقفت."""
        dg = _digest(session)
        due = self.last_write is None or (now - self.last_write).total_seconds() >= self.heartbeat
        if dg != self.last_digest or due:
            F.write_atomic(self.out, session)
            self.last_digest, self.last_write = dg, now
            return True
        return False

    def status(self, state: str, **kw):
        data = {"state": state, "updatedAt": dt.datetime.now().isoformat(timespec="seconds"),
                "lastSuccess": self.last_ok.isoformat(timespec="seconds") if self.last_ok else None, **kw}
        try:
            F.write_atomic(self.status_file, data)
        except OSError as e:
            log.error("تعذّر كتابة ملف الحالة: %s", e)

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    # ── دورة واحدة أثناء الجلسة ──
    def tick(self, now: dt.datetime) -> bool:
        try:
            session, warnings, n = self.snapshot(now)
        except Exception as e:
            self.close()                               # يُعاد الاتصال في الدورة التالية
            self.fail_since = self.fail_since or now
            log.error("فشل القراءة من قاعدة البيانات: %s", e)
            self.status("error", error=str(e), failingSince=self.fail_since.isoformat(timespec="seconds"))
            if now - self.fail_since >= self.stale:
                self.alerter.send("db-down", "توقفت تغذية الشاشة",
                                  f"تعذّرت القراءة من قاعدة بيانات نظام التداول منذ {self.fail_since:%H:%M}.\n"
                                  f"آخر خطأ: {e}\nالشاشة تعرض آخر بيانات سليمة.", now)
            return False
        if self.fail_since:
            self.alerter.send("db-up", "عادت تغذية الشاشة",
                              f"عادت القراءة من قاعدة البيانات عند {now:%H:%M} بعد انقطاع منذ {self.fail_since:%H:%M}.", now)
            self.alerter.clear("db-down")
        self.fail_since = None
        wrote = self.write_if_needed(session, now)
        self.last_ok = now
        for w in warnings:
            log.warning("تحذير بيانات: %s", w)
        recon = [w for w in warnings if w.startswith("مطابقة")]
        if recon and self.reconcile_alerted_for != now.date():
            self.reconcile_alerted_for = now.date()
            self.alerter.send("reconcile", "فروق في مطابقة بيانات الشاشة", "\n".join(recon), now)
        self.status("ok", rows=n, wrote=wrote, warnings=warnings[:20])
        return True

    # ── خارج وقت الجلسة ──
    def idle(self, now: dt.datetime):
        today = now.date()
        a, b = self.schedule.window(today)
        # أرشفة بيانات الجلسة بعد انتهاء نافذتها مباشرة
        if self.schedule.trading_day(today) and now > b and self.archived_for != today:
            if self.tick(now):                         # لقطة ختامية بعد الإقفال
                self.archive_session(today)
            self.archived_for = today
            self.close()
        hol = self.schedule.holiday(today)
        self.mark_holiday(hol)
        self.status("idle", holiday=hol, nextStart=self.schedule.next_start(now).isoformat(timespec="minutes"))

    def archive_session(self, d: dt.date):
        if self.out.exists():
            self.archive.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.out, self.archive / f"session-{d.isoformat()}.json")
            log.info("أُرشفت بيانات جلسة %s", d)

    def mark_holiday(self, holiday: str | None):
        """في العطلات الرسمية تُثبَّت الشاشة على «السوق مغلق»، وتعود للوضع الآلي بعدها."""
        data = F.load_json(self.out, None)
        if not data:
            return
        s = data.setdefault("session", {})
        if holiday and s.get("status") != "closed":
            s["status"], s["holiday"] = "closed", holiday
            F.write_atomic(self.out, data)
            log.info("عطلة رسمية (%s): ثُبّتت الشاشة على «السوق مغلق»", holiday)
        elif not holiday and s.get("holiday"):
            s["status"] = "auto"
            s.pop("holiday", None)
            F.write_atomic(self.out, data)

    def run(self):
        log.info("بدء التغذية من قاعدة البيانات — الجلسة %s–%s، كل %s ثانية",
                 self.schedule.open.strftime("%H:%M"), self.schedule.close.strftime("%H:%M"), self.interval)
        while True:
            now = dt.datetime.now()
            if self.schedule.active(now):
                self.tick(now)
                time.sleep(self.interval)
            else:
                self.idle(now)
                until = (self.schedule.next_start(now) - now).total_seconds()
                time.sleep(max(5, min(until, self.idle_check * 60)))


# ───────────────────────── قاعدة تجريبية ─────────────────────────
def make_demo_db(path: Path, session_json: Path):
    """قاعدة SQLite بنفس الشكل المقترح لجدول العرض — من ملف جلسة موجود — للتدريب والاختبار."""
    data = F.load_json(session_json, None)
    if not data:
        raise ValueError(f"تعذّر قراءة {session_json}")
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE prices (SYMBOL TEXT PRIMARY KEY, PREV_CLOSE REAL, OPEN_PRICE REAL, HIGH_PRICE REAL,
            LOW_PRICE REAL, LAST_PRICE REAL, VOLUME INTEGER, TRADE_VALUE REAL, TRADES INTEGER,
            BEST_BID REAL, BEST_ASK REAL, SHARES_OUTSTANDING INTEGER);
        CREATE TABLE idx (SESSION_DATE TEXT, INDEX_VALUE REAL, INDEX_PREV REAL, INDEX_HIGH REAL, INDEX_LOW REAL);
        CREATE VIEW LSM_DISPLAY_V AS SELECT * FROM prices;
        CREATE VIEW LSM_INDEX_V AS SELECT * FROM idx;
    """)
    for s in data["stocks"]:
        con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (s["sym"], s["prev"], s["open"], s["high"], s["low"], s["last"], s["vol"], s["val"],
                     s["trades"], s.get("bid"), s.get("ask"), s.get("shares")))
    i = data["index"]
    con.execute("INSERT INTO idx VALUES (?,?,?,?,?)",
                (data["session"]["date"], i["value"], i["prev"], i.get("high"), i.get("low")))
    con.commit()
    con.close()


# ───────────────────────── التشغيل ─────────────────────────
def setup_logging(cfg: Config | None, verbose: bool):
    F._utf8_console()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.handlers.clear()
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(fmt)
    log.addHandler(h)
    if cfg:
        lf = cfg.path_of("output", "log_file", "")
        if lf and cfg.get("output", "log_file"):
            lf.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(lf, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
            fh.setFormatter(fmt)
            log.addHandler(fh)


def run_test(feeder: DbFeeder) -> int:
    print("① الاتصال بقاعدة البيانات …")
    feeder.conn = connect(feeder.cfg)
    print("   ✔ تم الاتصال")
    cols, rows = fetch(feeder.conn, feeder.stock_sql)
    print(f"② استعلام الأسهم: {len(rows)} سطر — الأعمدة: {', '.join(cols)}")
    m = resolve_columns(cols, feeder.colmap)
    print("   مطابقة الأعمدة: " + ", ".join(f"{f}←{cols[i]}" for f, i in m.items()))
    missing = [f for f in ("sym", "prev", "last", "high", "low", "vol", "val", "trades") if f not in m]
    if missing:
        print("   ⚠ حقول غير موجودة (اختيارية أو تُشتق): " + ", ".join(missing))
    if feeder.index_sql:
        icols, irows = fetch(feeder.conn, feeder.index_sql)
        print(f"③ استعلام المؤشر: {index_from_rows(icols, irows, feeder.idxmap)}")
    session, warnings, n = feeder.snapshot()
    t = session["stocks"]
    print(f"④ النتيجة: جلسة {session['session']['date']} — {len(t)} شركة "
          f"({sum(1 for s in t if s['vol'] > 0)} متداولة)، المؤشر {session['index']['value']:,.2f}")
    for w in warnings:
        print("   تحذير:", w)
    print("✔ الاختبار ناجح — لم يُكتب أي ملف" if not warnings else "✔ الاتصال ناجح — راجع التحذيرات أعلاه")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="تغذية شاشة العرض مباشرة من قاعدة بيانات نظام التداول")
    ap.add_argument("--config", default=str(Path(__file__).resolve().parent / "db_feeder.ini"), help="ملف الإعداد")
    ap.add_argument("--test", action="store_true", help="اختبار الاتصال والأعمدة دون كتابة")
    ap.add_argument("--once", action="store_true", help="لقطة واحدة وكتابة الملف ثم خروج")
    ap.add_argument("--make-demo-db", metavar="SQLITE", help="إنشاء قاعدة تجريبية من ملف الجلسة الحالي")
    ap.add_argument("--from-session", default=str(F.DEFAULT_DATA_DIR / "session.json"), help="مصدر القاعدة التجريبية")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.make_demo_db:
        setup_logging(None, args.verbose)
        make_demo_db(Path(args.make_demo_db), Path(args.from_session))
        print(f"✔ أُنشئت القاعدة التجريبية: {args.make_demo_db}")
        return 0

    try:
        cfg = Config(Path(args.config))
        setup_logging(cfg, args.verbose)
        feeder = DbFeeder(cfg)
        if args.test:
            return run_test(feeder)
        if args.once:
            return 0 if feeder.tick(dt.datetime.now()) else 1
        feeder.run()
        return 0
    except KeyboardInterrupt:
        return 0
    except (ValueError, FileNotFoundError, ImportError) as e:
        hint = ""
        if isinstance(e, ImportError):
            hint = " — ثبّت مشغّل قاعدة البيانات (انظر requirements-db.txt)"
        print(f"خطأ: {e}{hint}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
