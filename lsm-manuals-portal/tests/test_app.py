# -*- coding: utf-8 -*-
"""اختبارات آلية للمنظومة:  python -m pytest -q"""
import importlib, io, json, os, re, shutil, sys, tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def appmod(monkeypatch):
    tmp = tempfile.mkdtemp()
    content = Path(tmp) / "content"
    shutil.copytree(ROOT / "content", content, ignore=shutil.ignore_patterns("archive"))
    monkeypatch.setenv("LSM_DATA_DIR", tmp)
    monkeypatch.setenv("LSM_CONTENT_DIR", str(content))
    monkeypatch.setenv("LSM_SECRET_KEY", "test-secret")
    if "app" in sys.modules:
        del sys.modules["app"]
    mod = importlib.import_module("app")
    mod.app.config["TESTING"] = True
    return mod


def token(client):
    client.get("/login")
    with client.session_transaction() as s:
        return s["_csrf"]


def login(client, u, p):
    t = token(client)
    return client.post("/login", data={"username": u, "password": p, "_csrf": t})


def post(client, url, **data):
    with client.session_transaction() as s:
        data["_csrf"] = s.get("_csrf", "")
    return client.post(url, data=data)


def admin_client(appmod):
    c = appmod.app.test_client()
    login(c, "admin", "Admin@2026")
    r = post(c, "/change-password", old="Admin@2026", new="NewPass2026", confirm="NewPass2026")
    assert r.status_code == 302
    return c


def add_user(appmod, c, username, dep="التداول", role="employee"):
    r = post(c, "/admin/user/add", username=username, fullname=username, department=dep,
             role=role, password="Temp12345")
    assert r.status_code == 302
    u = appmod.app.test_client()
    login(u, username, "Temp12345")
    post(u, "/change-password", old="Temp12345", new="Mine2026xx", confirm="Mine2026xx")
    return u


def test_csrf_required(appmod):
    c = appmod.app.test_client()
    r = c.post("/login", data={"username": "admin", "password": "Admin@2026"})
    assert r.status_code == 400


def test_must_change_enforced(appmod):
    c = appmod.app.test_client()
    login(c, "admin", "Admin@2026")
    r = c.get("/admin")
    assert r.status_code == 302 and "/change-password" in r.headers["Location"]


def test_open_redirect_blocked(appmod):
    c = admin_client(appmod)
    post(c, "/logout")
    t = token(c)
    r = c.post("/login?next=//evil.example", data={"username": "admin", "password": "NewPass2026", "_csrf": t})
    assert r.headers["Location"] == "/"


def test_lockout_after_failures(appmod):
    c = appmod.app.test_client()
    for _ in range(5):
        login(c, "admin", "wrong")
    r = login(c, "admin", "Admin@2026")
    assert r.status_code == 429


def test_deactivated_user_session_killed(appmod):
    a = admin_client(appmod)
    u = add_user(appmod, a, "m.ali")
    assert u.get("/").status_code == 200
    uid = appmod.sqlite3.connect(appmod.DB_PATH).execute(
        "SELECT id FROM users WHERE username='m.ali'").fetchone()[0]
    post(a, f"/admin/user/{uid}/toggle")
    r = u.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_last_admin_protected(appmod):
    a = admin_client(appmod)
    r = post(a, "/admin/user/1/edit", fullname="x", department="", role="employee")
    with appmod.app.app_context():
        assert appmod.db().execute("SELECT role FROM users WHERE id=1").fetchone()[0] == "admin"


def test_ack_is_version_aware(appmod, monkeypatch):
    a = admin_client(appmod)
    u = add_user(appmod, a, "s.omar")
    assert post(u, "/ack/forms").status_code == 302          # بدون تأكيد → لا يُسجّل
    with appmod.app.app_context():
        assert appmod.db().execute("SELECT COUNT(*) FROM acks").fetchone()[0] == 0
    post(u, "/ack/forms", confirm="1")
    assert "✔ تم الإقرار" in u.get("/").get_data(as_text=True)
    # رفع الإصدار يعيد طلب الإقرار
    data = [dict(m) for m in appmod.manifest()]
    for m in data:
        if m["slug"] == "forms":
            m["version"] = "9.9"
    monkeypatch.setattr(appmod, "manifest", lambda: data)
    html = u.get("/").get_data(as_text=True)
    assert "✔ تم الإقرار" not in html
    dg = a.get("/dg").get_data(as_text=True)
    assert "0٪" in dg


def test_search_arabic_normalization(appmod):
    a = admin_client(appmod)
    r = a.get("/search?q=" + "الاجراءات")       # بلا همزة يطابق «الإجراءات»
    html = r.get_data(as_text=True)
    assert "<mark>" in html and "نتيجة" in html


def test_csv_import_shows_generated_passwords_and_export_safe(appmod):
    a = admin_client(appmod)
    csv_data = "username,fullname,department,role,password\nx.one,=HYPERLINK(1),قسم,employee,\nbad user,ب,ق,,\n"
    with a.session_transaction() as s:
        t = s["_csrf"]
    r = a.post("/admin/import", data={"_csrf": t, "csvfile": (io.BytesIO(csv_data.encode()), "u.csv")},
               content_type="multipart/form-data")
    html = r.get_data(as_text=True)
    assert "x.one" in html and "كلمات المرور المؤقتة" in html
    exp = a.get("/admin/export-pending").get_data(as_text=True)
    assert "'=HYPERLINK" in exp


def test_security_headers(appmod):
    r = appmod.app.test_client().get("/login")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]


def test_all_pages_render(appmod):
    a = admin_client(appmod)
    for url in ["/", "/search", "/admin", "/dg", "/change-password", "/me", "/admin/manuals",
                "/admin/user/1"] + \
               [f"/manual/{m['slug']}" for m in appmod.manifest()]:
        assert a.get(url).status_code == 200, url
    assert a.get("/manual/nope").status_code == 404


def set_manifest(appmod, slug, **kw):
    p = appmod.CONTENT / "manifest.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for m in data:
        if m["slug"] == slug:
            m.update(kw)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    appmod._manifest_cache["mtime"] = None


def test_department_targeting(appmod):
    a = admin_client(appmod)
    u = add_user(appmod, a, "t.one", dep="التداول")
    add_user(appmod, a, "c.one", dep="المقاصة")
    set_manifest(appmod, "clearing", departments=["المقاصة"])
    html = u.get("/").get_data(as_text=True)
    assert "غير مطلوب من إدارتك" in html
    assert "أنجزت 0 من 5" in html
    dg = a.get("/dg").get_data(as_text=True)
    assert "(0/1)" in dg            # دليل المقاصة: موظف معني واحد فقط
    exp = a.get("/admin/export-pending").get_data(as_text=True)
    assert exp.count("\nt.one,") == 5 and exp.count("\nc.one,") == 6


def test_deadline_overdue(appmod):
    a = admin_client(appmod)
    u = add_user(appmod, a, "late.one")
    set_manifest(appmod, "forms", deadline="2020-01-01")
    assert "متأخر" in u.get("/").get_data(as_text=True)
    assert "تجاوزت المهلة" in u.get("/manual/forms").get_data(as_text=True)
    dg = a.get("/dg").get_data(as_text=True)
    assert "إقرارات متأخرة" in dg
    post(u, "/ack/forms", confirm="1")
    assert "دليل متأخر" not in u.get("/").get_data(as_text=True)


def _upload(c, url, fields, filename, content):
    with c.session_transaction() as s:
        fields["_csrf"] = s["_csrf"]
    fields["content"] = (io.BytesIO(content), filename)
    return c.post(url, data=fields, content_type="multipart/form-data")


def test_manual_new_version_archives_and_requires_reack(appmod):
    a = admin_client(appmod)
    u = add_user(appmod, a, "v.one")
    post(u, "/ack/forms", confirm="1")
    body = ("<html><body><p><strong>1. مقدمة</strong></p><p>" + "نص الدليل الجديد. " * 20 +
            "</p><script>alert(1)</script><a href=\"javascript:x()\" onclick=\"y()\">ر</a></body></html>")
    r = _upload(a, "/admin/manuals/forms/save",
                {"title": "ملحق النماذج الموحّدة", "version": "1.3", "status": "متاح",
                 "date": "", "deadline": "", "changes": "أُضيف نموذج جديد."}, "f.html", body.encode())
    assert r.status_code == 302
    html = (appmod.CONTENT / "forms.html").read_text(encoding="utf-8")
    assert "<script" not in html and "javascript:" not in html and "onclick" not in html
    assert '<h1 id="1-مقدمة">' in html
    assert list((appmod.CONTENT / "archive").glob("forms_v1.2_*.html"))
    page = u.get("/manual/forms").get_data(as_text=True)
    assert "أُضيف نموذج جديد." in page and "سبق أن أقررت بالإصدار (1.2)" in page
    assert "بانتظار إقرارك" in u.get("/").get_data(as_text=True)


def test_manual_add_and_validation(appmod):
    a = admin_client(appmod)
    r = post(a, "/admin/manuals/new", slug="Bad Slug", title="x", version="1.0", status="متاح")
    assert len(appmod.manifest()) == 6
    r = _upload(a, "/admin/manuals/new", {"slug": "risk", "title": "دليل المخاطر", "version": "1.0",
                "status": "متاح", "date": "", "deadline": "", "changes": ""},
                "r.html", ("<p>" + "إدارة المخاطر " * 20 + "</p>").encode())
    assert appmod.manual_by_slug("risk")["status"] == "متاح"
    assert a.get("/manual/risk").status_code == 200
    r = post(a, "/admin/manuals/risk/save", title="دليل المخاطر", version="abc", status="متاح")
    assert appmod.manual_by_slug("risk")["version"] == "1.0"


def test_record_and_backup(appmod):
    a = admin_client(appmod)
    u = add_user(appmod, a, "r.one")
    post(u, "/ack/trading", confirm="1")
    me = u.get("/me").get_data(as_text=True)
    assert "سجل الامتثال" in me and "1 من 6" in me
    assert u.get("/admin/user/1").status_code == 403
    r = a.get("/admin/backup")
    assert r.status_code == 200 and r.data[:15] == b"SQLite format 3"
