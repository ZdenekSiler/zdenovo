(function () {
  "use strict";

  function enhance() {
    var prose = document.querySelector(".prose-custom");
    if (!prose) return;

    wrapCodeBlocks(prose);
    classifyBlockquotes(prose);
    initMermaid();
    rehighlight(prose);
  }

  // ─── Reading progress bar ───
  function initProgress() {
    var bar = document.getElementById("reading-progress");
    if (!bar) return;
    window.addEventListener("scroll", function () {
      var h = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.width = h > 0 ? (window.scrollY / h * 100) + "%" : "0%";
    }, { passive: true });
  }

  // ─── Language display-name map for code block badges ───
  var LANG_DISPLAY_NAMES = {
    python: "Python",
    js: "JavaScript",
    javascript: "JavaScript",
    ts: "TypeScript",
    typescript: "TypeScript",
    bash: "Bash",
    sh: "Bash",
    shell: "Bash",
    yaml: "YAML",
    yml: "YAML",
    json: "JSON",
    toml: "TOML",
    html: "HTML",
    css: "CSS",
    sql: "SQL",
    dockerfile: "Dockerfile",
    go: "Go",
    rust: "Rust",
    cpp: "C++",
    c: "C",
    java: "Java",
    ruby: "Ruby"
  };

  function languageDisplayName(lang) {
    if (LANG_DISPLAY_NAMES.hasOwnProperty(lang)) return LANG_DISPLAY_NAMES[lang];
    return lang.charAt(0).toUpperCase() + lang.slice(1);
  }

  // ─── Copy button on code blocks ───
  function wrapCodeBlocks(prose) {
    var pres = prose.querySelectorAll("pre");
    var validationData = window.__codeValidation;
    pres.forEach(function (pre, i) {
      if (pre.parentElement.classList.contains("code-block-wrapper")) return;
      var code = pre.querySelector("code");
      if (code && code.classList.contains("language-mermaid")) return;
      var wrapper = document.createElement("div");
      wrapper.className = "code-block-wrapper";
      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(pre);

      var btn = document.createElement("button");
      btn.className = "copy-btn";
      btn.textContent = "Copy";
      btn.addEventListener("click", function () {
        var code = pre.querySelector("code");
        var text = code ? code.textContent : pre.textContent;
        navigator.clipboard.writeText(text).then(function () {
          btn.textContent = "Copied!";
          btn.classList.add("copied");
          setTimeout(function () {
            btn.textContent = "Copy";
            btn.classList.remove("copied");
          }, 2000);
        });
      });
      wrapper.appendChild(btn);

      var lines = (pre.querySelector("code") || pre).textContent.split("\n").length;
      var toggle = document.createElement("button");
      toggle.className = "code-toggle";
      toggle.textContent = "Hide";
      toggle.addEventListener("click", function () {
        var collapsed = pre.classList.toggle("code-collapsed");
        toggle.textContent = collapsed ? "Show (" + lines + " lines)" : "Hide";
      });
      wrapper.appendChild(toggle);

      var langClass = code && Array.prototype.find.call(code.classList, function (c) {
        return c.indexOf("language-") === 0;
      });
      if (langClass) {
        var lang = langClass.slice("language-".length);
        if (lang && lang !== "none" && lang !== "plain") {
          var langBadge = document.createElement("span");
          langBadge.className = "code-lang-badge";
          langBadge.textContent = languageDisplayName(lang);
          wrapper.appendChild(langBadge);
        }
      }

      if (validationData && validationData[i]) {
        var v = validationData[i];
        var icons = {valid: "✓", error: "✗", warning: "⚠", skipped: "—"};
        var badge = document.createElement("span");
        badge.className = "code-badge code-badge--" + v.status;
        badge.title = (v.language || "unknown") + ": " + v.message;
        badge.textContent = icons[v.status] || icons.skipped;
        wrapper.appendChild(badge);
      }
    });
  }

  // ─── Classify blockquotes as callouts ───
  function classifyBlockquotes(prose) {
    var bqs = prose.querySelectorAll("blockquote");
    bqs.forEach(function (bq) {
      var text = bq.textContent.trim();
      if (/^(⚠️|⚠|Warning:)/i.test(text)) {
        bq.classList.add("callout", "callout-warning");
      } else if (/^(❌|❗|Danger:|Critical:)/i.test(text)) {
        bq.classList.add("callout", "callout-danger");
      } else if (/^(✅|✔|Success:|Pro tip:)/i.test(text)) {
        bq.classList.add("callout", "callout-success");
      } else if (/^(💡|👉|Note:|Tip:|Info:)/i.test(text)) {
        bq.classList.add("callout");
      }
    });
  }

  // ─── Init Mermaid ───
  function initMermaid(retries) {
    if (typeof retries === "undefined") retries = 10;
    if (typeof mermaid === "undefined") {
      if (retries > 0) setTimeout(function () { initMermaid(retries - 1); }, 200);
      return;
    }
    document.querySelectorAll("pre > code.language-mermaid").forEach(function (code) {
      var pre = code.parentElement;
      var div = document.createElement("div");
      div.className = "mermaid";
      div.textContent = code.textContent;
      pre.parentElement.replaceChild(div, pre);
    });
    var targets = document.querySelectorAll(".mermaid:not([data-processed])");
    if (!targets.length) return;
    var isLight = document.documentElement.classList.contains("light");
    mermaid.initialize({
      startOnLoad: false,
      theme: isLight ? "default" : "dark",
      themeVariables: isLight ? {
        primaryColor: "#6366f1",
        primaryTextColor: "#18181b",
        primaryBorderColor: "#4f46e5",
        lineColor: "#6366f1",
        secondaryColor: "#e0e7ff",
        tertiaryColor: "#f4f4f5",
        background: "#ffffff",
        mainBkg: "#e0e7ff",
        nodeBorder: "#6366f1",
        clusterBkg: "#f4f4f5",
        titleColor: "#4338ca",
        edgeLabelBackground: "#ffffff"
      } : {
        primaryColor: "#4338ca",
        primaryTextColor: "#e4e4e7",
        primaryBorderColor: "#6366f1",
        lineColor: "#6366f1",
        secondaryColor: "#1e1b4b",
        tertiaryColor: "#27272a",
        background: "#18181b",
        mainBkg: "#1e1b4b",
        nodeBorder: "#6366f1",
        clusterBkg: "#27272a",
        titleColor: "#a5b4fc",
        edgeLabelBackground: "#18181b"
      }
    });
    mermaid.run({ querySelector: ".mermaid:not([data-processed])" });
  }

  // ─── Re-highlight with Prism after HTMX swap ───
  function rehighlight(prose) {
    if (typeof Prism !== "undefined") {
      Prism.highlightAllUnder(prose);
    }
  }

  // Run on initial load
  initProgress();
  enhance();

  // Re-run after HTMX content swaps
  document.body.addEventListener("htmx:afterSwap", function () {
    enhance();
  });
})();
