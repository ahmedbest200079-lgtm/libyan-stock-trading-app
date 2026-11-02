/* منظومة أدلة الإجراءات — سلوك الواجهة (ملف خارجي ليتوافق مع سياسة CSP) */
(function () {
  "use strict";

  // تأكيد الإجراءات الحساسة
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (!window.confirm(f.getAttribute("data-confirm"))) e.preventDefault();
    });
  });
  document.querySelectorAll("[data-print]").forEach(function (b) {
    b.addEventListener("click", function () { window.print(); });
  });

  // إدارة الأدلة: تنبيه عند رفع محتوى جديد دون رفع رقم الإصدار
  document.querySelectorAll("form.manform[data-version]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      var file = f.querySelector("input[type=file]"), ver = f.querySelector("input[name=version]");
      if (file && file.files.length && ver && ver.value.trim() === f.getAttribute("data-version") &&
          !window.confirm("رفعت محتوى جديداً دون تغيير رقم الإصدار، فلن يُطلب من الموظفين إقرار جديد. هل تريد المتابعة؟")) {
        e.preventDefault();
      }
    });
  });

  var doc = document.getElementById("doc");
  if (!doc) return;

  // ---- الفهرس الجانبي
  var box = document.getElementById("tocbox");
  var hs = doc.querySelectorAll("h1,h2");
  var links = [];
  box.innerHTML = "";
  hs.forEach(function (h, i) {
    if (!h.id) h.id = "sec-" + i;
    var a = document.createElement("a");
    a.href = "#" + h.id;
    a.textContent = h.textContent;
    if (h.tagName === "H2") a.className = "l2";
    box.appendChild(a);
    links.push(a);
  });
  if (!links.length) box.textContent = "لا عناوين في هذا الدليل.";

  var filter = document.getElementById("tocfilter");
  var norm = function (s) {
    return s.replace(/[ً-ٰٟـ]/g, "").replace(/[أإآ]/g, "ا")
      .replace(/ة/g, "ه").replace(/ى/g, "ي").toLowerCase();
  };
  if (filter) filter.addEventListener("input", function () {
    var q = norm(filter.value.trim());
    links.forEach(function (a) { a.style.display = !q || norm(a.textContent).indexOf(q) >= 0 ? "" : "none"; });
  });

  // ---- إبراز القسم الحالي في الفهرس
  if ("IntersectionObserver" in window && links.length) {
    var map = {};
    links.forEach(function (a) { map[a.getAttribute("href").slice(1)] = a; });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          links.forEach(function (a) { a.classList.remove("on"); });
          var a = map[en.target.id];
          if (a) { a.classList.add("on"); if (a.scrollIntoView && box.parentNode.scrollHeight > box.parentNode.clientHeight) a.scrollIntoView({ block: "nearest" }); }
        }
      });
    }, { rootMargin: "0px 0px -75% 0px" });
    hs.forEach(function (h) { io.observe(h); });
  }

  // ---- شريط تقدّم القراءة + تفعيل الإقرار بعد بلوغ نهاية الدليل
  var prog = document.getElementById("readprog");
  var btn = document.getElementById("ackbtn"), hint = document.getElementById("ackhint");
  var end = document.getElementById("docend");
  var reached = false;
  function unlock() {
    if (reached) return;
    reached = true;
    if (btn) btn.disabled = false;
    if (hint) hint.style.display = "none";
  }
  if (btn) btn.disabled = true;
  function onScroll() {
    var r = doc.getBoundingClientRect();
    var total = r.height - window.innerHeight;
    var p = total > 0 ? Math.min(100, Math.max(0, (-r.top / total) * 100)) : 100;
    if (prog) prog.style.width = p + "%";
    if (end && end.getBoundingClientRect().top <= window.innerHeight + 40) unlock();
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // ---- الطباعة
  var pb = document.getElementById("printbtn");
  if (pb) pb.addEventListener("click", function () { window.print(); });

  // ---- إبراز عبارة البحث القادمة من صفحة البحث
  var q = (doc.getAttribute("data-q") || "").trim();
  if (q.length >= 2) {
    var nq = norm(q), first = null, count = 0;
    var walker = document.createTreeWalker(doc, NodeFilter.SHOW_TEXT, null);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      var t = node.nodeValue, nt = "", pos = [];
      for (var i = 0; i < t.length; i++) {
        var c = norm(t[i]);
        if (!c) continue;
        nt += c; pos.push(i);
      }
      var idx = nt.indexOf(nq);
      if (idx < 0 || count > 300) return;
      var frag = document.createDocumentFragment(), last = 0;
      while (idx >= 0) {
        var a = pos[idx], b = pos[idx + nq.length - 1] + 1;
        frag.appendChild(document.createTextNode(t.slice(last, a)));
        var mk = document.createElement("mark");
        mk.textContent = t.slice(a, b);
        frag.appendChild(mk);
        if (!first) first = mk;
        count++; last = b;
        idx = nt.indexOf(nq, idx + nq.length);
      }
      frag.appendChild(document.createTextNode(t.slice(last)));
      node.parentNode.replaceChild(frag, node);
    });
    if (first) setTimeout(function () { first.scrollIntoView({ block: "center" }); }, 50);
  }
})();
