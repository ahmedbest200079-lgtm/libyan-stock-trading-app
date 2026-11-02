# -*- coding: utf-8 -*-
"""تحويل الفقرات العريضة إلى عناوين h1/h2 لبناء الفهرس الجانبي."""
import re, sys, html as H
from pathlib import Path

H1_SET = {"تنبيه حاكم", "ضبط الوثيقة", "المحتويات", "صيغة الاعتماد"}

def classify(text):
    t = text.strip()
    if re.match(r"^\d+\.\s", t): return 1
    if t.startswith("الملحق (") or t.startswith("الملاحق (أ"): return 1
    if "الأحكام التكميلية الحاكمة" in t and "الأقسام" in t: return 1
    if t in H1_SET: return 1
    if re.match(r"^\d+-\d+\s", t): return 2
    if t.startswith("نموذج "): return 2
    return 0

def process(path):
    src = Path(path).read_text(encoding="utf-8")
    # فقرة محتواها كله غامق: <p><strong> ... </strong></p>
    pat = re.compile(r"<p><strong>(.*?)</strong></p>", re.S)
    def repl(m):
        inner = m.group(1)
        plain = re.sub(r"<[^>]+>", "", inner)
        plain = H.unescape(re.sub(r"\s+", " ", plain)).strip()
        lvl = classify(plain)
        if lvl == 0:
            return m.group(0)
        anchor = re.sub(r"[^\w؀-ۿ]+", "-", plain).strip("-")[:60]
        return f'<h{lvl} id="{anchor}">{H.escape(plain)}</h{lvl}>'
    out = pat.sub(repl, src)
    Path(path).write_text(out, encoding="utf-8")
    print(path, "h1:", out.count("<h1"), "h2:", out.count("<h2"))

for f in sys.argv[1:]:
    process(f)
