(function () {
  var key = "edumeeting-color-scheme";
  var root = document.documentElement;
  var stored = null;
  try { stored = localStorage.getItem(key); } catch (e) {}
  var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  root.setAttribute("data-md-color-scheme", stored || (prefersDark ? "slate" : "default"));
  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-theme-toggle]")) return;
    var next = root.getAttribute("data-md-color-scheme") === "slate" ? "default" : "slate";
    root.setAttribute("data-md-color-scheme", next);
    try { localStorage.setItem(key, next); } catch (e) {}
  });
  document.addEventListener("click", function (event) {
    var link = event.target.closest(".md-sidebar--primary a[href^='#']");
    var drawer = document.getElementById("md-drawer");
    if (link && drawer) drawer.checked = false;
  });
})();