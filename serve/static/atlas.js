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

// Robust source citations, shared by every page that links to a paper.
// Corpus DOIs are sometimes stored with a resolver prefix ("dx.doi.org/10.…",
// "https://doi.org/10.…", "doi:10.…") or are blank; naively prepending
// https://doi.org/ then yields https://doi.org/dx.doi.org/… → 404. And a missing
// first_author was being shown as a bare "?". Normalize here so links resolve and
// labels are meaningful, with the PMC page / PMCID as the honest fallback.
window.AtlasCite = (function () {
  function cleanDoi(doi) {
    if (!doi) return null;
    var d = String(doi).trim()
      .replace(/^https?:\/\//i, "")   // strip scheme
      .replace(/^(dx\.)?doi\.org\//i, "")  // strip resolver host
      .replace(/^doi:/i, "")          // strip doi: prefix
      .trim();
    return d.indexOf("10.") === 0 ? d : null;  // only link things that look like a DOI
  }
  function pmcUrl(pmcid) {
    return pmcid
      ? "https://www.ncbi.nlm.nih.gov/pmc/articles/" + encodeURIComponent(pmcid) + "/"
      : null;
  }
  return {
    cleanDoi: cleanDoi,
    // Best source URL: a clean DOI, else the PMC article page, else "#".
    href: function (p) {
      if (!p) return "#";
      var d = cleanDoi(p.doi);
      if (d) return "https://doi.org/" + d;
      return pmcUrl(p.pmcid) || "#";
    },
    // "Author year", falling back to the PMCID — never a bare "?".
    label: function (p) {
      if (!p) return "";
      var a = (p.first_author && String(p.first_author).trim()) || p.pmcid || "";
      return (a + " " + (p.year || "")).trim();
    },
  };
})();
