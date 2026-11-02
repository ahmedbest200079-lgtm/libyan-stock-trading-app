# -*- coding: utf-8 -*-
"""
منظومة أدلة الإجراءات الداخلية — شركة سوق المال الليبي
تشغيل:  python app.py   ثم فتح  http://localhost:8000
حساب المدير الافتراضي عند أول تشغيل:  admin / Admin@2026  (تُلزم المنظومة بتغييره عند أول دخول)

متغيرات البيئة (اختيارية):
  LSM_DATA_DIR    مجلد قاعدة البيانات والمفتاح السري (الافتراضي: مجلد التطبيق)
  LSM_HOST/LSM_PORT  عنوان ومنفذ الاستماع (الافتراضي 0.0.0.0:8000)
  LSM_HTTPS=1     عند التشغيل خلف وكيل HTTPS (يفعّل ملفات تعريف الارتباط الآمنة)
  LSM_SECRET_KEY  مفتاح الجلسات (وإلا يُولَّد ويُحفظ في ملف .secret_key)
"""
import csv, hmac, io, json, os, re, secrets, sqlite3, sys
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LSM_DATA_DIR") or BASE)
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "data.db"
CONTENT = BASE / "content"
SECRET_FILE = DATA_DIR / ".secret_key"

AVAILABLE = "متاح"
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,40}$")


def _secret_key():
    env = os.environ.get("LSM_SECRET_KEY")
    if env:
        return env
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32))
        try:
            os.chmod(SECRET_FILE, 0o600)
        except OSError:
            pass
    return SECRET_FILE.read_text().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("LSM_HTTPS") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,   # حد رفع ملفات CSV
)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- قاعدة البيانات
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_=None):
    d = g.pop("db", None)
    if d:
        d.close()


def _add_column(con, table, col, ddl):
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")   # قراءات متزامنة أفضل عند تعدد المستخدمين
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        fullname TEXT NOT NULL,
        department TEXT DEFAULT '',
        role TEXT NOT NULL DEFAULT 'employee',   -- admin / employee
        active INTEGER NOT NULL DEFAULT 1,
        must_change INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS acks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        manual_slug TEXT NOT NULL,
        manual_version TEXT NOT NULL,
        acked_at TEXT NOT NULL,
        UNIQUE(user_id, manual_slug, manual_version)
    );
    CREATE TABLE IF NOT EXISTS audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL, username TEXT, action TEXT, detail TEXT
    );
    """)
    # ترحيل آمن لقواعد بيانات النسخة السابقة
    _add_column(con, "users", "failed_count", "INTEGER NOT NULL DEFAULT 0")
    _add_column(con, "users", "locked_until", "TEXT")
    _add_column(con, "users", "last_login", "TEXT")
    _add_column(con, "acks", "ip", "TEXT DEFAULT ''")
    _add_column(con, "audit", "ip", "TEXT DEFAULT ''")
    con.executescript("""
    CREATE INDEX IF NOT EXISTS ix_acks_slug_ver ON acks(manual_slug, manual_version);
    CREATE INDEX IF NOT EXISTS ix_audit_at ON audit(at);
    """)
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        con.execute(
            "INSERT INTO users(username,password_hash,fullname,department,role,active,must_change,created_at) "
            "VALUES(?,?,?,?,?,1,1,?)",
            ("admin", generate_password_hash("Admin@2026"), "مدير المنظومة",
             "الإدارة العامة", "admin", now_iso()))
    con.commit()
    con.close()


def client_ip():
    return (request.remote_addr or "")[:64]


def log(action, detail="", username=None):
    db().execute("INSERT INTO audit(at,username,action,detail,ip) VALUES(?,?,?,?,?)",
                 (now_iso(), username or session.get("username", "-"), action, detail, client_ip()))
    db().commit()


# ---------------------------------------------------------------- الأدلة
_manifest_cache = {"mtime": None, "data": []}
_text_cache = {}


def manifest():
    """يقرأ manifest.json مع تخزين مؤقت حسب وقت التعديل، ويتحقق من سلامته."""
    p = CONTENT / "manifest.json"
    mt = p.stat().st_mtime
    if _manifest_cache["mtime"] != mt:
        data = json.loads(p.read_text(encoding="utf-8"))
        seen = set()
        for m in data:
            for k in ("slug", "title", "version", "status", "file"):
                if k not in m:
                    raise ValueError(f"manifest.json: الحقل «{k}» ناقص في {m}")
            if m["slug"] in seen:
                raise ValueError(f"manifest.json: المعرّف «{m['slug']}» مكرر")
            seen.add(m["slug"])
            m.setdefault("date", "")
            m["version"] = str(m["version"])
        _manifest_cache.update(mtime=mt, data=data)
    return _manifest_cache["data"]


def available_manuals():
    return [m for m in manifest() if m["status"] == AVAILABLE]


def manual_by_slug(slug):
    for m in manifest():
        if m["slug"] == slug:
            return m
    return None


def manual_path(m):
    p = (CONTENT / m["file"]).resolve()
    if CONTENT.resolve() not in p.parents:   # منع الخروج من مجلد المحتوى
        abort(404)
    return p


def manual_html(m):
    p = manual_path(m)
    if not p.exists():
        abort(404)
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------- البحث العربي
_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_CHARMAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي",
                          "ة": "ه", "ؤ": "و", "ئ": "ي",
                          "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
                          "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9"})


def normalize_ar(s):
    return _DIACRITICS.sub("", s).translate(_CHARMAP).lower()


def strip_tags(h):
    import html as H
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def searchable(m):
    """نص الدليل الخام + نسخته المطبّعة + خريطة المواقع (مخزنة حسب وقت التعديل)."""
    p = manual_path(m)
    mt = p.stat().st_mtime
    c = _text_cache.get(m["slug"])
    if c and c[0] == mt:
        return c[1]
    text = strip_tags(p.read_text(encoding="utf-8"))
    norm, pos = [], []
    for i, ch in enumerate(text):
        if _DIACRITICS.match(ch):
            continue
        norm.append(ch.translate(_CHARMAP).lower())
        pos.append(i)
    val = (text, "".join(norm), pos)
    _text_cache[m["slug"]] = (mt, val)
    return val


# ---------------------------------------------------------------- الحماية: CSRF وترويسات الأمان
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


@app.before_request
def protect_and_load_user():
    session.permanent = True
    if request.method == "POST":
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
        if not sent or not hmac.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "انتهت صلاحية النموذج أو الطلب غير صالح — أعد تحميل الصفحة وحاول مجدداً.")
    g.user = None
    uid = session.get("uid")
    if uid:
        row = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row or not row["active"]:
            # الحساب أُوقف أو حُذف أثناء الجلسة — تُنهى فوراً
            session.clear()
            flash("انتهت جلستك أو أُوقف الحساب.", "error")
            return redirect(url_for("login"))
        g.user = row
        session["role"], session["fullname"] = row["role"], row["fullname"]
        if row["must_change"] and request.endpoint not in ("change_password", "logout", "static"):
            return redirect(url_for("change_password"))


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
    if session.get("uid") and request.endpoint != "static":
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------------- حراسة الدخول
def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not g.get("user"):
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return f(*a, **k)
    return w


def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if not g.get("user") or g.user["role"] != "admin":
            abort(403)
        return f(*a, **k)
    return w


def safe_next(target):
    """منع إعادة التوجيه إلى مواقع خارجية (Open Redirect)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("dashboard")


@app.context_processor
def inject():
    return {"now_year": datetime.now().year, "csrf_token": csrf_token}


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
def http_error(e):
    msgs = {400: "طلب غير صالح.", 403: "ليست لديك صلاحية الوصول إلى هذه الصفحة.",
            404: "الصفحة المطلوبة غير موجودة.", 413: "حجم الملف المرفوع يتجاوز الحد المسموح (2 ميجابايت)."}
    desc = getattr(e, "description", "") if e.code == 400 else ""
    return render_template("error.html", code=e.code,
                           msg=desc if desc and not desc.startswith("The ") else msgs.get(e.code)), e.code


# ---------------------------------------------------------------- كلمات المرور
def password_problem(new, username=""):
    if len(new) < 8:
        return "كلمة المرور يجب ألا تقل عن 8 أحرف."
    if not re.search(r"[A-Za-z؀-ۿ]", new) or not re.search(r"\d", new):
        return "كلمة المرور يجب أن تحتوي على أحرف وأرقام معاً."
    if username and username.lower() in new.lower():
        return "لا يجوز أن تتضمن كلمة المرور اسم المستخدم."
    return None


def temp_password():
    # كلمة مؤقتة تستوفي السياسة (أحرف + أرقام) وسهلة الإملاء
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz"
    return "".join(secrets.choice(alphabet) for _ in range(6)) + "".join(
        secrets.choice("23456789") for _ in range(4))


# ---------------------------------------------------------------- الدخول والخروج
@app.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        row = db().execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        now = datetime.now()
        if row and row["locked_until"] and row["locked_until"] > now.isoformat(timespec="seconds"):
            log("login_locked", "", username=u)
            flash(f"الحساب مقفل مؤقتاً بسبب محاولات دخول خاطئة متكررة. حاول بعد {LOCK_MINUTES} دقيقة أو راجع مدير المنظومة.", "error")
            return render_template("login.html"), 429
        if row and row["active"] and check_password_hash(row["password_hash"], p):
            db().execute("UPDATE users SET failed_count=0, locked_until=NULL, last_login=? WHERE id=?",
                         (now_iso(), row["id"]))
            db().commit()
            nxt = request.args.get("next")
            session.clear()
            session["uid"], session["username"] = row["id"], row["username"]
            session["fullname"], session["role"] = row["fullname"], row["role"]
            csrf_token()
            log("login")
            if row["must_change"]:
                flash("يرجى تغيير كلمة المرور قبل المتابعة.", "warn")
                return redirect(url_for("change_password"))
            return redirect(safe_next(nxt))
        if row:
            fails = row["failed_count"] + 1
            locked = (now + timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds") \
                if fails >= MAX_FAILED_LOGINS else None
            db().execute("UPDATE users SET failed_count=?, locked_until=? WHERE id=?",
                         (0 if locked else fails, locked, row["id"]))
            db().commit()
            if locked:
                log("account_locked", f"after {fails} failures", username=u)
        log("login_failed", "", username=u or "-")
        flash("بيانات الدخول غير صحيحة أو الحساب موقوف.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    if session.get("uid"):
        log("logout")
    session.clear()
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old = request.form.get("old", "")
        new = request.form.get("new", "")
        confirm = request.form.get("confirm", "")
        row = g.user
        problem = password_problem(new, row["username"])
        if not check_password_hash(row["password_hash"], old):
            flash("كلمة المرور الحالية غير صحيحة.", "error")
        elif new != confirm:
            flash("تأكيد كلمة المرور غير مطابق.", "error")
        elif problem:
            flash(problem, "error")
        elif check_password_hash(row["password_hash"], new):
            flash("كلمة المرور الجديدة يجب أن تختلف عن الحالية.", "error")
        else:
            db().execute("UPDATE users SET password_hash=?, must_change=0 WHERE id=?",
                         (generate_password_hash(new), row["id"]))
            db().commit()
            log("change_password")
            flash("تم تغيير كلمة المرور.", "ok")
            return redirect(url_for("dashboard"))
    return render_template("change_password.html", forced=bool(g.user["must_change"]))


# ---------------------------------------------------------------- الواجهات
def current_acks(user_id):
    """الأدلة التي أقرّ بها المستخدم على إصدارها الحالي فقط: {slug: acked_at}."""
    cur = {m["slug"]: m["version"] for m in available_manuals()}
    out = {}
    for r in db().execute("SELECT manual_slug, manual_version, acked_at FROM acks WHERE user_id=?",
                          (user_id,)):
        if cur.get(r["manual_slug"]) == r["manual_version"]:
            out[r["manual_slug"]] = r["acked_at"]
    return out


@app.route("/")
@login_required
def dashboard():
    acked = current_acks(g.user["id"])
    mans = []
    for m in manifest():
        mm = dict(m)
        mm["acked"] = m["status"] == AVAILABLE and m["slug"] in acked
        mm["acked_at"] = acked.get(m["slug"], "")[:16].replace("T", " ")
        mans.append(mm)
    avail = [m for m in mans if m["status"] == AVAILABLE]
    done = sum(1 for m in avail if m["acked"])
    return render_template("dashboard.html", manuals=mans, done=done, need=len(avail),
                           pct=round(100 * done / len(avail)) if avail else 0)


@app.route("/manual/<slug>")
@login_required
def manual(slug):
    m = manual_by_slug(slug) or abort(404)
    if m["status"] != AVAILABLE:
        return render_template("manual.html", m=m, body=None, acked=False)
    body = manual_html(m)
    acked = db().execute(
        "SELECT acked_at FROM acks WHERE user_id=? AND manual_slug=? AND manual_version=?",
        (g.user["id"], slug, m["version"])).fetchone()
    return render_template("manual.html", m=m, body=body, acked=acked,
                           q=request.args.get("q", "")[:100])


@app.route("/ack/<slug>", methods=["POST"])
@login_required
def ack(slug):
    m = manual_by_slug(slug) or abort(404)
    if m["status"] != AVAILABLE:
        abort(404)
    if request.form.get("confirm") != "1":
        flash("يرجى تأكيد الإقرار بوضع علامة في خانة التأكيد.", "error")
        return redirect(url_for("manual", slug=slug) + "#ackbar")
    try:
        db().execute("INSERT INTO acks(user_id,manual_slug,manual_version,acked_at,ip) VALUES(?,?,?,?,?)",
                     (g.user["id"], slug, m["version"], now_iso(), client_ip()))
        db().commit()
        log("ack", f"{slug} v{m['version']}")
        flash("تم تسجيل إقرارك بالاطلاع على هذا الدليل.", "ok")
    except sqlite3.IntegrityError:
        pass
    return redirect(url_for("manual", slug=slug))


@app.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()[:100]
    nq = normalize_ar(q).strip()
    results, total = [], 0
    if len(nq) >= 2:
        for m in available_manuals():
            text, norm, pos = searchable(m)
            hits, count, start = [], 0, 0
            while True:
                i = norm.find(nq, start)
                if i < 0:
                    break
                count += 1
                if len(hits) < 5:
                    a, b = pos[i], pos[i + len(nq) - 1] + 1
                    s, e = max(0, a - 80), min(len(text), b + 80)
                    hits.append({"pre": ("…" if s else "") + text[s:a], "hit": text[a:b],
                                 "post": text[b:e] + ("…" if e < len(text) else "")})
                start = i + len(nq)
            if count:
                total += count
                results.append({"m": m, "hits": hits, "count": count})
        results.sort(key=lambda r: -r["count"])
        log("search", q)
    return render_template("search.html", q=q, results=results, total=total)


# ---------------------------------------------------------------- لوحة المدير
def active_admins_count(exclude_id=None):
    sql = "SELECT COUNT(*) FROM users WHERE role='admin' AND active=1"
    args = ()
    if exclude_id is not None:
        sql += " AND id<>?"
        args = (exclude_id,)
    return db().execute(sql, args).fetchone()[0]


def ack_map():
    """{(user_id, slug): acked_at} للإصدارات الحالية فقط."""
    cur = {m["slug"]: m["version"] for m in available_manuals()}
    out = {}
    for r in db().execute("SELECT user_id, manual_slug, manual_version, acked_at FROM acks"):
        if cur.get(r["manual_slug"]) == r["manual_version"]:
            out[(r["user_id"], r["manual_slug"])] = r["acked_at"][:16].replace("T", " ")
    return out


@app.route("/admin", methods=["GET"])
@login_required
@admin_required
def admin(generated=None):
    q = request.args.get("q", "").strip()
    sql = "SELECT * FROM users"
    args = ()
    if q:
        sql += " WHERE username LIKE ? OR fullname LIKE ? OR department LIKE ?"
        args = (f"%{q}%",) * 3
    users = db().execute(sql + " ORDER BY role DESC, active DESC, fullname", args).fetchall()
    deps = [r[0] for r in db().execute(
        "SELECT DISTINCT department FROM users WHERE department<>'' ORDER BY department")]
    return render_template("admin.html", users=users, mans=available_manuals(),
                           ackmap=ack_map(), generated=generated, q=q, deps=deps,
                           now=now_iso())


def _clean_user_fields(form):
    return (form.get("username", "").strip(), form.get("fullname", "").strip()[:120],
            form.get("department", "").strip()[:120],
            "admin" if form.get("role") == "admin" else "employee")


@app.route("/admin/user/add", methods=["POST"])
@login_required
@admin_required
def admin_add_user():
    u, fn, dep, role = _clean_user_fields(request.form)
    pw = request.form.get("password", "").strip()
    if not u or not fn:
        flash("اسم المستخدم والاسم الكامل مطلوبان.", "error")
        return redirect(url_for("admin"))
    if not USERNAME_RE.match(u):
        flash("اسم المستخدم يقبل الأحرف اللاتينية والأرقام والنقطة والشرطة فقط (2–40 حرفاً).", "error")
        return redirect(url_for("admin"))
    if pw and password_problem(pw):
        flash("كلمة المرور المؤقتة: " + password_problem(pw), "error")
        return redirect(url_for("admin"))
    pw = pw or temp_password()
    try:
        db().execute("INSERT INTO users(username,password_hash,fullname,department,role,active,must_change,created_at) "
                     "VALUES(?,?,?,?,?,1,1,?)",
                     (u, generate_password_hash(pw), fn, dep, role, now_iso()))
        db().commit()
        log("add_user", f"{u} ({role})")
        flash(f"أُنشئ الحساب ({u}) — كلمة المرور المؤقتة: {pw} — تظهر مرة واحدة فقط.", "ok")
    except sqlite3.IntegrityError:
        flash("اسم المستخدم مستخدم من قبل.", "error")
    return redirect(url_for("admin"))


@app.route("/admin/user/<int:uid>/<action>", methods=["POST"])
@login_required
@admin_required
def admin_user_action(uid, action):
    row = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() or abort(404)
    me = row["id"] == g.user["id"]
    if action == "toggle":
        if me:
            flash("لا يمكنك إيقاف حسابك الحالي.", "error")
        elif row["active"] and row["role"] == "admin" and active_admins_count(exclude_id=uid) == 0:
            flash("لا يمكن إيقاف آخر مدير منظومة نشط.", "error")
        else:
            db().execute("UPDATE users SET active=1-active WHERE id=?", (uid,))
            db().commit()
            log("toggle_user", f"{row['username']} → {'موقوف' if row['active'] else 'نشط'}")
    elif action == "reset":
        pw = temp_password()
        db().execute("UPDATE users SET password_hash=?, must_change=1, failed_count=0, locked_until=NULL "
                     "WHERE id=?", (generate_password_hash(pw), uid))
        db().commit()
        log("reset_password", row["username"])
        flash(f"كلمة المرور المؤقتة للمستخدم ({row['username']}): {pw} — تظهر مرة واحدة فقط.", "ok")
    elif action == "unlock":
        db().execute("UPDATE users SET failed_count=0, locked_until=NULL WHERE id=?", (uid,))
        db().commit()
        log("unlock_user", row["username"])
        flash(f"أُلغي قفل الحساب ({row['username']}).", "ok")
    elif action == "edit":
        _, fn, dep, role = _clean_user_fields(request.form)
        if not fn:
            flash("الاسم الكامل مطلوب.", "error")
        elif row["role"] == "admin" and role != "admin" and active_admins_count(exclude_id=uid) == 0:
            flash("لا يمكن تحويل آخر مدير منظومة نشط إلى موظف.", "error")
        else:
            db().execute("UPDATE users SET fullname=?, department=?, role=? WHERE id=?",
                         (fn, dep, role, uid))
            db().commit()
            log("edit_user", f"{row['username']}: {row['department']}/{row['role']} → {dep}/{role}")
            flash(f"حُدّثت بيانات ({row['username']}).", "ok")
    else:
        abort(404)
    return redirect(url_for("admin", q=request.args.get("q") or None))


@app.route("/admin/import", methods=["POST"])
@login_required
@admin_required
def admin_import():
    f = request.files.get("csvfile")
    if not f or not f.filename:
        flash("اختر ملف CSV أولاً.", "error")
        return redirect(url_for("admin"))
    try:
        data = f.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("ترميز الملف غير مدعوم — احفظه بصيغة CSV UTF-8.", "error")
        return redirect(url_for("admin"))
    reader = csv.DictReader(io.StringIO(data))
    if not reader.fieldnames or not {"username", "fullname"} <= {c.strip() for c in reader.fieldnames}:
        flash("الملف يجب أن يحتوي على الأعمدة: username, fullname (و department, role, password اختيارياً).", "error")
        return redirect(url_for("admin"))
    added, skipped, generated = 0, [], []
    for n, row in enumerate(reader, start=2):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        u, fn = row.get("username", ""), row.get("fullname", "")[:120]
        if not u or not fn:
            skipped.append(f"سطر {n}: بيانات ناقصة"); continue
        if not USERNAME_RE.match(u):
            skipped.append(f"سطر {n}: اسم مستخدم غير صالح ({u})"); continue
        pw = row.get("password", "")
        if pw and password_problem(pw):
            skipped.append(f"سطر {n}: كلمة مرور ضعيفة ({u})"); continue
        auto = not pw
        pw = pw or temp_password()
        role = "admin" if row.get("role") == "admin" else "employee"
        try:
            db().execute("INSERT INTO users(username,password_hash,fullname,department,role,active,must_change,created_at) "
                         "VALUES(?,?,?,?,?,1,1,?)",
                         (u, generate_password_hash(pw), fn, row.get("department", "")[:120], role, now_iso()))
            added += 1
            if auto:
                generated.append({"username": u, "fullname": fn, "password": pw})
        except sqlite3.IntegrityError:
            skipped.append(f"سطر {n}: مكرر ({u})")
    db().commit()
    log("import_users", f"added={added} skipped={len(skipped)}")
    flash(f"الاستيراد: أُضيف {added}، وتُخطي {len(skipped)}.", "ok")
    for s in skipped[:15]:
        flash(s, "warn")
    # كلمات المرور المولّدة تُعرض مرة واحدة في الصفحة نفسها (لا تُخزّن في الجلسة)
    return admin(generated=generated) if generated else redirect(url_for("admin"))


def csv_safe(v):
    """منع حقن الصيغ عند فتح الملف في Excel."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def csv_response(header, rows, name):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    for r in rows:
        w.writerow([csv_safe(x) for x in r])
    data = io.BytesIO(("﻿" + out.getvalue()).encode("utf-8"))
    return send_file(data, as_attachment=True, download_name=name, mimetype="text/csv")


@app.route("/admin/export-acks")
@login_required
@admin_required
def export_acks():
    titles = {m["slug"]: m for m in manifest()}
    rows = []
    for r in db().execute(
            "SELECT u.username,u.fullname,u.department,a.manual_slug,a.manual_version,a.acked_at,a.ip "
            "FROM acks a JOIN users u ON u.id=a.user_id ORDER BY a.acked_at"):
        m = titles.get(r["manual_slug"], {})
        current = "نعم" if m.get("version") == r["manual_version"] else "لا (إصدار سابق)"
        rows.append([r["username"], r["fullname"], r["department"], m.get("title", r["manual_slug"]),
                     r["manual_version"], current, r["acked_at"].replace("T", " "), r["ip"]])
    log("export", "acks")
    return csv_response(["المستخدم", "الاسم الكامل", "الإدارة", "الدليل", "الإصدار",
                         "الإصدار الحالي؟", "تاريخ الإقرار", "عنوان IP"], rows,
                        f"acknowledgments_{datetime.now():%Y%m%d}.csv")


@app.route("/admin/export-pending")
@login_required
@admin_required
def export_pending():
    am = ack_map()
    rows = []
    for u in db().execute("SELECT * FROM users WHERE active=1 AND role='employee' ORDER BY department, fullname"):
        for m in available_manuals():
            if (u["id"], m["slug"]) not in am:
                rows.append([u["username"], u["fullname"], u["department"], m["title"], m["version"]])
    log("export", "pending")
    return csv_response(["المستخدم", "الاسم الكامل", "الإدارة", "الدليل غير المُقَرّ به", "الإصدار"],
                        rows, f"pending_acks_{datetime.now():%Y%m%d}.csv")


@app.route("/admin/export-audit")
@login_required
@admin_required
def export_audit():
    rows = [[r["at"].replace("T", " "), r["username"], r["action"], r["detail"], r["ip"]]
            for r in db().execute("SELECT * FROM audit ORDER BY id DESC LIMIT 50000")]
    log("export", "audit")
    return csv_response(["الوقت", "المستخدم", "الإجراء", "التفاصيل", "عنوان IP"], rows,
                        f"audit_{datetime.now():%Y%m%d}.csv")


# ---------------------------------------------------------------- لوحة المدير العام
ACTION_LABELS = {
    "login": "دخول", "logout": "خروج", "login_failed": "محاولة دخول فاشلة",
    "login_locked": "محاولة على حساب مقفل", "account_locked": "قفل حساب تلقائي",
    "ack": "إقرار اطلاع", "add_user": "إضافة مستخدم", "edit_user": "تعديل مستخدم",
    "reset_password": "تهيئة كلمة مرور", "toggle_user": "تفعيل/إيقاف", "unlock_user": "إلغاء قفل",
    "import_users": "استيراد مستخدمين", "change_password": "تغيير كلمة مرور",
    "search": "بحث", "export": "تصدير تقرير",
}


@app.route("/dg")
@login_required
@admin_required
def dg_dashboard():
    d = db()
    mans = available_manuals()
    need = len(mans)
    employees = d.execute("SELECT id, fullname, department FROM users "
                          "WHERE active=1 AND role='employee'").fetchall()
    total_users = len(employees)
    all_users = d.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    am = ack_map()
    emp_done = {e["id"]: sum(1 for m in mans if (e["id"], m["slug"]) in am) for e in employees}

    per_manual = []
    for m in mans:
        c = sum(1 for e in employees if (e["id"], m["slug"]) in am)
        per_manual.append({"title": m["title"], "slug": m["slug"], "version": m["version"],
                           "count": c, "total": total_users,
                           "pct": round(100 * c / total_users) if total_users else 0})
    # النسبة الكلية = الإقرارات المنجزة ÷ الإقرارات المطلوبة (موزونة فعلياً)
    req = total_users * need
    overall = round(100 * sum(emp_done.values()) / req) if req else 0
    fully_done = sum(1 for v in emp_done.values() if need and v >= need)

    deps = {}
    for e in employees:
        k = e["department"] or "غير محدد"
        x = deps.setdefault(k, {"total": 0, "acked": 0, "acks": 0})
        x["total"] += 1
        x["acks"] += emp_done[e["id"]]
        if need and emp_done[e["id"]] >= need:
            x["acked"] += 1
    per_dep = [{"dep": k, "total": v["total"], "acked": v["acked"],
                "pct": round(100 * v["acks"] / (v["total"] * need)) if v["total"] and need else 0}
               for k, v in sorted(deps.items(), key=lambda kv: kv[1]["acks"] / max(1, kv[1]["total"]))]

    pending = sorted(
        [{"fullname": e["fullname"], "department": e["department"], "done": emp_done[e["id"]], "need": need}
         for e in employees if emp_done[e["id"]] < need],
        key=lambda p: (p["done"], p["fullname"]))
    today = datetime.now().strftime("%Y-%m-%d")
    logins_today = d.execute("SELECT COUNT(*) FROM audit WHERE action='login' AND at>=?", (today,)).fetchone()[0]
    failed_today = d.execute("SELECT COUNT(*) FROM audit WHERE action IN ('login_failed','login_locked') AND at>=?",
                             (today,)).fetchone()[0]
    locked_now = d.execute("SELECT COUNT(*) FROM users WHERE locked_until>?", (now_iso(),)).fetchone()[0]
    never_logged = d.execute("SELECT COUNT(*) FROM users WHERE active=1 AND role='employee' AND last_login IS NULL"
                             ).fetchone()[0]
    recent_acks = d.execute(
        "SELECT u.fullname, u.department, a.manual_slug, a.manual_version, a.acked_at FROM acks a "
        "JOIN users u ON u.id=a.user_id ORDER BY a.acked_at DESC LIMIT 10").fetchall()
    recent_audit = d.execute(
        "SELECT at, username, action, detail FROM audit WHERE action<>'search' ORDER BY id DESC LIMIT 12").fetchall()
    titles = {m["slug"]: m["title"] for m in manifest()}
    return render_template("dg.html", overall=overall, total_users=total_users, fully_done=fully_done,
                           all_users=all_users, manuals_count=need,
                           per_manual=per_manual, per_dep=per_dep,
                           logins_today=logins_today, failed_today=failed_today, locked_now=locked_now,
                           never_logged=never_logged, recent_acks=recent_acks,
                           recent_audit=recent_audit, titles=titles,
                           pending=pending[:10], pending_total=len(pending), labels=ACTION_LABELS)


# ---------------------------------------------------------------- أوامر الصيانة
@app.cli.command("reset-admin")
def reset_admin_cmd():
    """استعادة الدخول: إنشاء/تهيئة حساب admin بكلمة مؤقتة (flask --app app reset-admin)."""
    with app.app_context():
        pw = temp_password()
        d = db()
        if d.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
            d.execute("UPDATE users SET password_hash=?, role='admin', active=1, must_change=1, "
                      "failed_count=0, locked_until=NULL WHERE username='admin'", (generate_password_hash(pw),))
        else:
            d.execute("INSERT INTO users(username,password_hash,fullname,department,role,active,must_change,created_at) "
                      "VALUES('admin',?,'مدير المنظومة','الإدارة العامة','admin',1,1,?)",
                      (generate_password_hash(pw), now_iso()))
        d.execute("INSERT INTO audit(at,username,action,detail,ip) VALUES(?,?,?,?,?)",
                  (now_iso(), "cli", "reset_password", "admin", "local"))
        d.commit()
        print(f"admin / {pw}  (يُطلب تغييرها عند أول دخول)")


# ----------------------------------------------------------------
init_db()
manifest()   # يفشل مبكراً برسالة واضحة إن كان manifest.json تالفاً

if __name__ == "__main__":
    host = os.environ.get("LSM_HOST", "0.0.0.0")
    port = int(os.environ.get("LSM_PORT", "8000"))
    try:
        from waitress import serve
        print(f"تشغيل عبر waitress على http://{host}:{port}")
        serve(app, host=host, port=port, threads=8)
    except ImportError:
        print("تنبيه: waitress غير مثبت — يُستخدم خادم Flask التطويري.", file=sys.stderr)
        app.run(host=host, port=port, debug=False)
