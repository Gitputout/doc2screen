(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };

  /* theme */
  var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  var theme = store.get("d2s-theme", mq && mq.matches ? "dark" : "light");
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    var m = $("#metaTheme"); if (m) m.setAttribute("content", t === "dark" ? "#101314" : "#f5f1e8");
  }
  applyTheme(theme);
  var btnTheme = $("#btnTheme");
  if (btnTheme) btnTheme.addEventListener("click", function () {
    theme = theme === "dark" ? "light" : "dark";
    applyTheme(theme); store.set("d2s-theme", theme);
  });

  /* font size */
  var fs = parseInt(store.get("d2s-fs", "0"), 10) ||
    parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--fs")) || 17;
  function applyFs(v) {
    fs = Math.max(13, Math.min(24, v));
    document.documentElement.style.setProperty("--fs", fs + "px");
    var el = $("#fsVal"); if (el) el.textContent = Math.round(fs);
    store.set("d2s-fs", String(fs));
  }
  applyFs(fs);
  var minus = $("#fsMinus"), plus = $("#fsPlus");
  if (minus) minus.addEventListener("click", function () { applyFs(fs - 1); });
  if (plus) plus.addEventListener("click", function () { applyFs(fs + 1); });

  /* progress / topbar */
  var progress = $("#progress"), topbar = $("#topbar");
  function onScroll() {
    var h = document.documentElement, y = h.scrollTop || document.body.scrollTop || 0;
    var max = h.scrollHeight - h.clientHeight;
    if (progress) progress.style.width = (max > 0 ? Math.min(100, y / max * 100) : 0) + "%";
    if (topbar) topbar.classList.toggle("scrolled", y > 6);
  }
  document.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* drawer */
  var drawer = $("#drawer"), scrim = $("#scrim"), btnToc = $("#btnToc");
  function openNav() {
    if (!drawer) return;
    drawer.classList.add("open"); if (scrim) scrim.hidden = false;
    requestAnimationFrame(function () { if (scrim) scrim.classList.add("on"); });
    document.body.style.overflow = "hidden";
    if (btnToc) btnToc.setAttribute("aria-expanded", "true");
    drawer.setAttribute("aria-hidden", "false");
  }
  function closeNav() {
    if (!drawer) return;
    drawer.classList.remove("open"); if (scrim) scrim.classList.remove("on");
    setTimeout(function () { if (scrim && !drawer.classList.contains("open")) scrim.hidden = true; }, 260);
    document.body.style.overflow = "";
    if (btnToc) btnToc.setAttribute("aria-expanded", "false");
    drawer.setAttribute("aria-hidden", "true");
  }
  if (btnToc) btnToc.addEventListener("click", openNav);
  var btnClose = $("#btnClose"); if (btnClose) btnClose.addEventListener("click", closeNav);
  if (scrim) scrim.addEventListener("click", closeNav);
  $$("#drawer a").forEach(function (a) { a.addEventListener("click", closeNav); });
  var drawerTop = $("#btnDrawerTop");
  if (drawerTop) drawerTop.addEventListener("click", function () { closeNav(); window.scrollTo({ top: 0, behavior: "smooth" }); });

  /* image viewer */
  var viewer = $("#viewer"), vImg = $("#viewerImg"), vTitle = $("#viewerTitle"), stage = $("#stage");
  function openViewer(fig) {
    if (!viewer || !fig) return;
    var img = fig.querySelector("img");
    if (!img) return;
    vImg.src = img.src; vImg.alt = img.alt || "";
    vTitle.textContent = (fig.querySelector(".cap-text") || {}).textContent || "";
    var m = fig.getAttribute("data-mode");
    stage.classList.toggle("rot", m === "rot" || m === "strip");
    viewer.hidden = false; document.body.style.overflow = "hidden";
  }
  function closeViewer() {
    if (!viewer) return;
    viewer.hidden = true; vImg.removeAttribute("src"); document.body.style.overflow = "";
  }
  var vClose = $("#vClose"), vRot = $("#vRot");
  if (vClose) vClose.addEventListener("click", closeViewer);
  if (vRot) vRot.addEventListener("click", function () { stage.classList.toggle("rot"); });
  if (viewer) viewer.addEventListener("click", function (e) { if (e.target === viewer || e.target === stage) closeViewer(); });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (viewer && !viewer.hidden) closeViewer();
    else if (drawer && drawer.classList.contains("open")) closeNav();
  });

  $$(".shot").forEach(function (fig) {
    var box = fig.querySelector(".shot-box"), img = fig.querySelector("img");
    if (!box || !img) return;
    var base = fig.getAttribute("data-base");
    function applyMode(mode) {
      box.className = "shot-box is-" + mode;
      fig.setAttribute("data-mode", mode);
      var hint = fig.querySelector(".mode-hint");
      if (hint) hint.textContent = mode === "rot" ? "已旋转 90°" : mode === "strip" ? "左右滑动" : "点击放大";
      if (mode === "strip") box.scrollLeft = 0;
    }
    var rot = fig.querySelector('[data-act="rotate"]');
    if (rot) rot.addEventListener("click", function () {
      var cur = fig.getAttribute("data-mode");
      if (cur !== base) { applyMode(base); return; }
      applyMode(base === "rot" ? "fit" : "rot");
    });
    var zoom = fig.querySelector('[data-act="zoom"]');
    if (zoom) zoom.addEventListener("click", function () { openViewer(fig); });
    img.addEventListener("click", function () { openViewer(fig); });
  });

  /* copy code */
  function fallbackCopy(text, btn) {
    var ta = document.createElement("textarea"); ta.value = text;
    ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta);
    ta.select(); var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta); flash(btn, ok ? "已复制" : "复制失败");
  }
  function flash(btn, msg) {
    var old = btn.textContent; btn.textContent = msg;
    setTimeout(function () { btn.textContent = old; }, 1200);
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest(".copy") : null;
    if (!btn) return;
    var code = btn.closest(".code-block") && btn.closest(".code-block").querySelector("code");
    var text = code ? code.textContent : "";
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { flash(btn, "已复制"); },
        function () { fallbackCopy(text, btn); });
    } else fallbackCopy(text, btn);
  });
})();
