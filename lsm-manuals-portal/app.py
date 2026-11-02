# -*- coding: utf-8 -*-
"""
منظومة أدلة الإجراءات الداخلية — شركة سوق المال الليبي
تشغيل:  python app.py   ثم فتح  http://localhost:8000
حساب المدير الافتراضي عند أول تشغيل:  admin / Admin@2026  (غيّره فوراً)
"""
import csv, io, json, os, re, sqlite3, secrets
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "data.db"
CONTENT = BASE / "content"
SECRET_FILE = BASE / ".secret_key"

if not SECRET_FILE.exists():
    SECRET_FILE.write_text(secrets.token_hex(32))
app = Flask(__name__)
app.secret_key = SECRET_FILE.read_text().strip()

# ---------------------------------------------------------------- قاعدة البيانات
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    d = g.pop("db", None)
    if d: d.close()

def init_db():
    con = sqlite3.connect(DB_PATH)
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
    cur = con.execute("SELECT COUNT(*) c FROM users")
    if cur.fetchone()[0] == 0:
        con.execute(
            "INSERT INTO users(username,password_hash,fullname,department,role,active,must_change,created_at) "
            "VALUES(?,?,?,?,?,1,1,?)",
            ("admin", generate_password_hash("Admin@2026"), "مدير المنظومة",
             "الإدارة العامة", "admin", datetime.now().isoformat(timespec="seconds")))
    con.commit(); con.close()

def log(action, detail=""):
    db().execute("INSERT INTO audit(at,username,action,detail) VALUES(?,?,?,?)",
                 (datetime.now().isoformat(timespec="seconds"),
                  session.get("username", "-"), action, detail))
    db().commit()

# ---------------------------------------------------------------- الأدلة
def manifest():
    return json.loads((CONTENT / "manifest.json").read_text(encoding="utf-8"))

def manual_by_slug(slug):
    for m in manifest():
        if m["slug"] == slug: return m
    return None

def manual_html(m):
    return (CONTENT / m["file"]).read_text(encoding="utf-8")

def strip_tags(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))

# ---------------------------------------------------------------- حراسة الدخول
def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("uid"): return redirect(url_for("login", next=request.path))
        return f(*a, **k)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if session.get("role") != "admin": abort(403)
        return f(*a, **k)
    return w

@app.context_processor
def inject():
    return {"now_year": datetime.now().year}

# ---------------------------------------------------------------- الدخول والخروج
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        row = db().execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        if row and row["active"] and check_password_hash(row["password_hash"], p):
            session.clear()
            session["uid"], session["username"] = row["id"], row["username"]
            session["fullname"], session["role"] = row["fullname"], row["role"]
            log("login")
            if row["must_change"]:
                flash("يرجى تغيير كلمة المرور قبل المتابعة.", "warn")
                return redirect(url_for("change_password"))
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("بيانات الدخول غير صحيحة أو الحساب موقوف.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    log("logout"); session.clear()
    return redirect(url_for("login"))

@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old = request.form.get("old", ""); new = request.form.get("new", "")
        row = db().execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
        if not check_password_hash(row["password_hash"], old):
            flash("كلمة المرور الحالية غير صحيحة.", "error")
        elif len(new) < 8:
            flash("كلمة المرور الجديدة يجب ألا تقل عن 8 أحرف.", "error")
        else:
            db().execute("UPDATE users SET password_hash=?, must_change=0 WHERE id=?",
                         (generate_password_hash(new), session["uid"]))
            db().commit(); log("change_password")
            flash("تم تغيير كلمة المرور.", "ok")
            return redirect(url_for("dashboard"))
    return render_template("change_password.html")

# ---------------------------------------------------------------- الواجهات
@app.route("/")
@login_required
def dashboard():
    acked = {r["manual_slug"] for r in db().execute(
        "SELECT manual_slug FROM acks a JOIN users u ON u.id=a.user_id "
        "WHERE a.user_id=? ", (session["uid"],))}
    mans = []
    for m in manifest():
        mm = dict(m); mm["acked"] = m["slug"] in acked and m["status"] == "متاح"
        mans.append(mm)
    return render_template("dashboard.html", manuals=mans)

@app.route("/manual/<slug>")
@login_required
def manual(slug):
    m = manual_by_slug(slug) or abort(404)
    if m["status"] != "متاح":
        return render_template("manual.html", m=m, body=None, acked=False)
    body = manual_html(m)
    acked = db().execute(
        "SELECT 1 FROM acks WHERE user_id=? AND manual_slug=? AND manual_version=?",
        (session["uid"], slug, m["version"])).fetchone() is not None
    return render_template("manual.html", m=m, body=body, acked=acked)

@app.route("/ack/<slug>", methods=["POST"])
@login_required
def ack(slug):
    m = manual_by_slug(slug) or abort(404)
    try:
        db().execute("INSERT INTO acks(user_id,manual_slug,manual_version,acked_at) VALUES(?,?,?,?)",
                     (session["uid"], slug, m["version"],
                      datetime.now().isoformat(timespec="seconds")))
        db().commit(); log("ack", f"{slug} v{m['version']}")
        flash("تم تسجيل إقرارك بالاطلاع على هذا الدليل.", "ok")
    except sqlite3.IntegrityError:
        pass
    return redirect(url_for("manual", slug=slug))

@app.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()
    results = []
    if len(q) >= 2:
        for m in manifest():
            if m["status"] != "متاح": continue
            text = strip_tags(manual_html(m))
            hits = []
            for mt in re.finditer(re.escape(q), text):
                s, e = max(0, mt.start() - 70), min(len(text), mt.end() + 70)
                hits.append("…" + text[s:e] + "…")
                if len(hits) >= 5: break
            if hits:
                results.append({"m": m, "hits": hits, "count": len(list(re.finditer(re.escape(q), text)))})
    return render_template("search.html", q=q, results=results)

# ---------------------------------------------------------------- لوحة المدير
@app.route("/admin", methods=["GET"])
@login_required
@admin_required
def admin():
    users = db().execute("SELECT * FROM users ORDER BY role DESC, fullname").fetchall()
    mans = [m for m in manifest() if m["status"] == "متاح"]
    rows = db().execute(
        "SELECT u.id uid, a.manual_slug, a.manual_version, a.acked_at "
        "FROM acks a JOIN users u ON u.id=a.user_id").fetchall()
    ackmap = {(r["uid"], r["manual_slug"]): r["acked_at"][:16].replace("T", " ") for r in rows}
    return render_template("admin.html", users=users, mans=mans, ackmap=ackmap)

@app.route("/admin/user/add", methods=["POST"])
@login_required
@admin_required
def admin_add_user():
    u = request.form.get("username", "").strip()
    fn = request.form.get("fullname", "").strip()
    dep = request.form.get("department", "").strip()
    role = "admin" if request.form.get("role") == "admin" else "employee"
    pw = request.form.get("password") or secrets.token_urlsafe(8)
    if not u or not fn:
        flash("اسم المستخدم والاسم الكامل مطلوبان.", "error")
        return redirect(url_for("admin"))
    try:
        db().execute("INSERT INTO users(username,password_hash,fullname,department,role,active,must_change,created_at) "
                     "VALUES(?,?,?,?,?,1,1,?)",
                     (u, generate_password_hash(pw), fn, dep, role,
                      datetime.now().isoformat(timespec="seconds")))
        db().commit(); log("add_user", u)
        flash(f"أُنشئ الحساب ({u}) — كلمة المرور المؤقتة: {pw}", "ok")
    except sqlite3.IntegrityError:
        flash("اسم المستخدم مستخدم من قبل.", "error")
    return redirect(url_for("admin"))

@app.route("/admin/user/<int:uid>/<action>", methods=["POST"])
@login_required
@admin_required
def admin_user_action(uid, action):
    row = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() or abort(404)
    if action == "toggle":
        if row["username"] == session["username"]:
            flash("لا يمكنك إيقاف حسابك الحالي.", "error")
        else:
            db().execute("UPDATE users SET active=1-active WHERE id=?", (uid,))
            db().commit(); log("toggle_user", row["username"])
    elif action == "reset":
        pw = secrets.token_urlsafe(8)
        db().execute("UPDATE users SET password_hash=?, must_change=1 WHERE id=?",
                     (generate_password_hash(pw), uid))
        db().commit(); log("reset_password", row["username"])
        flash(f"كلمة المرور المؤقتة للمستخدم ({row['username']}): {pw}", "ok")
    return redirect(url_for("admin"))

@app.route("/admin/import", methods=["POST"])
@login_required
@admin_required
def admin_import():
    f = request.files.get("csvfile")
    if not f:
        flash("اختر ملف CSV أولاً.", "error"); return redirect(url_for("admin"))
    data = f.read().decode("utf-8-sig")
    added, skipped = 0, 0
    for row in csv.DictReader(io.StringIO(data)):
        u = (row.get("username") or "").strip()
        fn = (row.get("fullname") or "").strip()
        if not u or not fn: skipped += 1; continue
        pw = (row.get("password") or "").strip() or secrets.token_urlsafe(8)
        role = "admin" if (row.get("role") or "").strip() == "admin" else "employee"
        try:
            db().execute("INSERT INTO users(username,password_hash,fullname,department,role,active,must_change,created_at) "
                         "VALUES(?,?,?,?,?,1,1,?)",
                         (u, generate_password_hash(pw), fn,
                          (row.get("department") or "").strip(), role,
                          datetime.now().isoformat(timespec="seconds")))
            added += 1
        except sqlite3.IntegrityError:
            skipped += 1
    db().commit(); log("import_users", f"added={added} skipped={skipped}")
    flash(f"الاستيراد: أُضيف {added}، وتُخطي {skipped} (مكرر أو ناقص).", "ok")
    return redirect(url_for("admin"))

@app.route("/admin/export-acks")
@login_required
@admin_required
def export_acks():
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["المستخدم", "الاسم الكامل", "الإدارة", "الدليل", "الإصدار", "تاريخ الإقرار"])
    for r in db().execute(
        "SELECT u.username,u.fullname,u.department,a.manual_slug,a.manual_version,a.acked_at "
        "FROM acks a JOIN users u ON u.id=a.user_id ORDER BY a.acked_at"):
        title = (manual_by_slug(r["manual_slug"]) or {}).get("title", r["manual_slug"])
        w.writerow([r["username"], r["fullname"], r["department"], title,
                    r["manual_version"], r["acked_at"]])
    data = io.BytesIO(("﻿" + out.getvalue()).encode("utf-8"))
    return send_file(data, as_attachment=True, download_name="acknowledgments.csv",
                     mimetype="text/csv")


# ---------------------------------------------------------------- لوحة المدير العام
@app.route("/dg")
@login_required
@admin_required
def dg_dashboard():
    d = db()
    mans = [m for m in manifest() if m["status"] == "متاح"]
    total_users = d.execute("SELECT COUNT(*) c FROM users WHERE active=1 AND role='employee'").fetchone()["c"]
    all_users = d.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    # نسبة الإقرار لكل دليل (من الموظفين النشطين)
    per_manual = []
    for m in mans:
        c = d.execute("SELECT COUNT(DISTINCT a.user_id) c FROM acks a JOIN users u ON u.id=a.user_id "
                      "WHERE a.manual_slug=? AND a.manual_version=? AND u.active=1 AND u.role='employee'",
                      (m["slug"], m["version"])).fetchone()["c"]
        pct = round(100 * c / total_users) if total_users else 0
        per_manual.append({"title": m["title"], "slug": m["slug"], "count": c,
                           "total": total_users, "pct": pct})
    overall = round(sum(x["pct"] for x in per_manual) / len(per_manual)) if per_manual else 0
    # التغطية بحسب الإدارة
    deps = {}
    for r in d.execute("SELECT id, department FROM users WHERE active=1 AND role='employee'"):
        deps.setdefault(r["department"] or "غير محدد", {"total": 0, "acked": 0})
        deps[r["department"] or "غير محدد"]["total"] += 1
    need = len(mans)
    for r in d.execute(
        "SELECT u.department dep, a.user_id uid, COUNT(DISTINCT a.manual_slug) c "
        "FROM acks a JOIN users u ON u.id=a.user_id "
        "WHERE u.active=1 AND u.role='employee' GROUP BY a.user_id"):
        if r["c"] >= need and need > 0:
            deps.setdefault(r["dep"] or "غير محدد", {"total": 0, "acked": 0})
            deps[r["dep"] or "غير محدد"]["acked"] += 1
    per_dep = [{"dep": k, "total": v["total"], "acked": v["acked"],
                "pct": round(100 * v["acked"] / v["total"]) if v["total"] else 0}
               for k, v in sorted(deps.items())]
    # النشاط
    logins_today = d.execute("SELECT COUNT(*) c FROM audit WHERE action='login' AND at>=?",
                             (datetime.now().strftime("%Y-%m-%d"),)).fetchone()["c"]
    recent_acks = d.execute(
        "SELECT u.fullname, u.department, a.manual_slug, a.acked_at FROM acks a "
        "JOIN users u ON u.id=a.user_id ORDER BY a.acked_at DESC LIMIT 10").fetchall()
    recent_audit = d.execute(
        "SELECT at, username, action, detail FROM audit ORDER BY id DESC LIMIT 12").fetchall()
    titles = {m["slug"]: m["title"] for m in manifest()}
    pending = []
    if mans:
        for r in d.execute(
            "SELECT u.id, u.fullname, u.department, "
            "(SELECT COUNT(DISTINCT a.manual_slug) FROM acks a WHERE a.user_id=u.id) c "
            "FROM users u WHERE u.active=1 AND u.role='employee' ORDER BY c ASC, u.fullname LIMIT 10"):
            if r["c"] < need:
                pending.append({"fullname": r["fullname"], "department": r["department"],
                                "done": r["c"], "need": need})
    return render_template("dg.html", overall=overall, total_users=total_users,
                           all_users=all_users, manuals_count=len(mans),
                           per_manual=per_manual, per_dep=per_dep,
                           logins_today=logins_today, recent_acks=recent_acks,
                           recent_audit=recent_audit, titles=titles, pending=pending)

# ----------------------------------------------------------------
init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
