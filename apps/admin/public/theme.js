// Anti-FOUC theme bootstrap (loaded by index.html before any stylesheet or module).
// Tiny and free of imports: every branch must run in a single tick. Kept as a file,
// not an inline script, so the admin's CSP can forbid inline script entirely.
(function () {
  try {
    var stored = localStorage.getItem("csmarket.admin.theme") || "dark";
    document.documentElement.setAttribute("data-theme", stored);
  } catch (e) {
    document.documentElement.setAttribute("data-theme", "dark");
  }
})();
