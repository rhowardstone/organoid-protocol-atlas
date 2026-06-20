// Replace the default Datasette favicon with the organoid-cluster icon, site-wide.
(function () {
  document.querySelectorAll("link[rel~='icon']").forEach((l) => l.remove());
  const link = document.createElement("link");
  link.rel = "icon";
  link.type = "image/svg+xml";
  link.href = "/static/favicon.svg";
  document.head.appendChild(link);
})();

// Global theme toggle (dark / light), persisted in localStorage. Loaded on every
// Datasette page via extra_js_urls. Applies before paint where possible to avoid flash.
(function () {
  const KEY = "apa-theme";
  const root = document.documentElement;

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    const btn = document.getElementById("apa-theme-btn");
    if (btn) btn.textContent = theme === "dark" ? "☀ light" : "☾ dark";
  }

  // apply stored preference ASAP
  const stored = (() => { try { return localStorage.getItem(KEY); } catch (e) { return null; } })();
  apply(stored || "light");

  function toggle() {
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    try { localStorage.setItem(KEY, next); } catch (e) {}
    apply(next);
  }

  function injectButton() {
    if (document.getElementById("apa-theme-btn")) return;
    const btn = document.createElement("button");
    btn.id = "apa-theme-btn";
    btn.className = "apa-theme-btn";
    btn.type = "button";
    btn.setAttribute("aria-label", "Toggle dark mode");
    btn.addEventListener("click", toggle);
    document.body.appendChild(btn);
    apply(root.getAttribute("data-theme") || "light");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectButton);
  } else {
    injectButton();
  }
})();
