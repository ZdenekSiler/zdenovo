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

  // ─── Table of contents from h2s ───
  function buildToc(prose) {
    var toc = document.getElementById("toc");
    if (!toc) return;
    var headings = prose.querySelectorAll("h2");
    if (headings.length < 2) { toc.style.display = "none"; return; }

    var title = document.createElement("div");
    title.className = "toc-title";
    title.textContent = "In this post";
    toc.appendChild(title);

    var ol = document.createElement("ol");
    headings.forEach(function (h, i) {
      var id = "section-" + i;
      h.id = id;
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = "#" + id;
      a.textContent = h.textContent;
      li.appendChild(a);
      ol.appendChild(li);
    });
    toc.appendChild(ol);
  }

  // ─── Copy button on code blocks ───
  function wrapCodeBlocks(prose) {
    var pres = prose.querySelectorAll("pre");
    pres.forEach(function (pre) {
      if (pre.parentElement.classList.contains("code-block-wrapper")) return;
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
    mermaid.initialize({
      startOnLoad: false,
      theme: "dark",
      themeVariables: {
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
