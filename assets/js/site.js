/* site.js — 全站唯一脚本（计划书 §5.1）。
   功能只有两个：手机抽屉开合（§2.4.3）、页脚年份（静态回退值已写在 HTML 里）。
   约定：不用 innerHTML / document.write / eval / fetch / localStorage（断言 S13）；
   不用 Element.closest（老 X5 保险，手写 parentNode 循环）。 */
(function () {
  "use strict";
  var body = document.body;
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("site-nav");
  var scrim = document.querySelector(".nav-scrim");
  if (!toggle || !nav || !scrim) { return; }

  function isOpen() { return body.classList.contains("nav-open"); }

  function open() {
    body.classList.add("nav-open");
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "关闭菜单");
    scrim.hidden = false;
    var first = nav.querySelector("a");
    if (first) { first.focus(); }
  }

  function close(restoreFocus) {
    body.classList.remove("nav-open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "打开菜单");
    scrim.hidden = true;
    if (restoreFocus) { toggle.focus(); }
  }

  toggle.addEventListener("click", function () {
    if (isOpen()) { close(true); } else { open(); }
  });
  scrim.addEventListener("click", function () { close(true); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && isOpen()) { close(true); }
  });
  nav.addEventListener("click", function (e) {
    var t = e.target;
    while (t && t !== nav) {
      if (t.tagName === "A") { close(false); return; }
      t = t.parentNode;
    }
  });

  var y = document.getElementById("foot-year");
  if (y) { y.textContent = String(new Date().getFullYear()); }
})();
