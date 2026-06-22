// Highlight the active nav link based on current path
(function () {
  const links = document.querySelectorAll("header nav a");
  const path = window.location.pathname;

  links.forEach((link) => {
    const href = link.getAttribute("href");
    const isActive =
      href === "/"
        ? path === "/"
        : path === href || path.startsWith(href + "/");

    if (isActive) {
      link.classList.add("text-zinc-100");
      link.classList.remove("text-zinc-400");
    }
  });
})();

// Rotating terminal widget — cycles every 10 seconds
(function () {
  const $ = (s, c) => `<span class="${s}">${c}</span>`;
  const cmd  = (t) => `<p class="truncate">${$("text-indigo-400","$")} ${$("text-zinc-400", t)}</p>`;
  const ok   = (t) => `<p class="truncate">${$("text-emerald-400","✓")} ${$("text-emerald-400", t)}</p>`;
  const err  = (t) => `<p class="truncate">${$("text-red-400","✗")} ${$("text-red-400", t)}</p>`;
  const out  = (t) => `<p class="truncate">${$("text-zinc-800","·")} ${$("text-zinc-600", t)}</p>`;
  const sql  = (t) => `<p class="truncate">${$("text-violet-400","&gt;")} ${$("text-zinc-400", t)}</p>`;
  const cont = (t) => `<p class="truncate">${$("text-zinc-700","  ")} ${$("text-zinc-500", t)}</p>`;
  const cursor = () => `<p class="flex items-center gap-1">${$("text-indigo-400","$")} <span class="inline-block w-1.5 h-3 bg-indigo-400 animate-pulse"></span></p>`;

  const TERMINALS = [
    {
      label: "zdenovo — bash",
      lines: [
        cmd("git push origin main"),
        ok("Build passed. Deploying..."),
        err("Deploy failed."),
        cmd(`git commit -m ${$("text-emerald-300", '"fix: trust me"')}`),
        cmd("git push origin main"),
        ok("Deploy successful."),
        cursor(),
      ],
    },
    {
      label: "zdenovo — python",
      lines: [
        cmd("python app.py"),
        err("ModuleNotFoundError: 'fastapi'"),
        cmd("pip install fastapi uvicorn"),
        ok("Successfully installed."),
        cmd("python app.py"),
        ok("Uvicorn running on :8000"),
        cursor(),
      ],
    },
    {
      label: "zdenovo — docker",
      lines: [
        cmd("docker build -t app:latest ."),
        err("COPY failed: file not found"),
        cmd("ls"),
        out("Dockerfile  app/  pyproject.toml"),
        cmd("docker build -t app:latest ."),
        ok("Successfully built 3f9a1c2"),
        cursor(),
      ],
    },
    {
      label: "zdenovo — node",
      lines: [
        cmd("npm install"),
        out("added 847 packages in 12s"),
        err("3 high severity vulnerabilities"),
        cmd("npm audit fix --force"),
        ok("fixed 3 of 3 issues"),
        cmd("npm run build"),
        ok("dist/ ready in 1.2s"),
      ],
    },
    {
      label: "zdenovo — psql",
      lines: [
        cmd("psql -U admin prod_db"),
        sql("SELECT COUNT(*) FROM users;"),
        out("1 row: 142857"),
        sql("DELETE FROM sessions;"),
        err("ERROR: permission denied"),
        sql("GRANT DELETE ON sessions TO admin;"),
        cursor(),
      ],
    },
    {
      label: "zdenovo — curl",
      lines: [
        cmd("curl -X POST /api/posts"),
        err("422 Unprocessable Entity"),
        cmd("curl -X POST /api/posts \\"),
        cont('-H "Content-Type: application/json"'),
        err("401 Unauthorized"),
        cmd("curl ... -H &quot;Authorization: Bearer …&quot;"),
        ok("201 Created"),
      ],
    },
  ];

  const titleEl = document.getElementById("terminal-title");
  const bodyEl  = document.getElementById("terminal-body");
  if (!titleEl || !bodyEl) return;

  let current = 0;

  function rotate() {
    current = (current + 1) % TERMINALS.length;
    const t = TERMINALS[current];

    bodyEl.style.opacity = "0";
    setTimeout(() => {
      titleEl.textContent = t.label;
      bodyEl.innerHTML = t.lines.join("");
      bodyEl.style.opacity = "1";
    }, 200);
  }

  setInterval(rotate, 300000);
})();

// Typing effect for hero heading
(function () {
  function typeHeading() {
    var el = document.getElementById("typed-heading");
    var cursor = document.getElementById("typed-cursor");
    if (!el || el.dataset.typed) return;
    el.dataset.typed = "1";

    var text = "Deploy. Fail. Fix.\nRepeat.";
    var i = 0;

    function tick() {
      if (i >= text.length) {
        if (cursor) cursor.classList.add("done");
        revealHeroContent();
        return;
      }
      var ch = text[i];
      if (ch === "\n") {
        el.appendChild(document.createElement("br"));
      } else {
        el.appendChild(document.createTextNode(ch));
      }
      i++;
      setTimeout(tick, ch === "." ? 180 : 55);
    }

    setTimeout(tick, 300);
  }

  function revealHeroContent() {
    document.querySelectorAll(".hero-reveal").forEach(function (el, i) {
      setTimeout(function () { el.classList.add("visible"); }, i * 150);
    });
  }

  typeHeading();
  document.body.addEventListener("htmx:afterSwap", typeHeading);
})();

// Scroll-triggered reveal animations
(function () {
  var revealCount = 0;

  function initReveal() {
    revealCount = 0;
    var elements = document.querySelectorAll(".scroll-reveal:not(.visible)");
    if (!elements.length) return;

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          revealCount++;
          var el = entry.target;
          setTimeout(function () { el.classList.add("visible"); }, revealCount * 120);
          observer.unobserve(el);
        }
      });
    }, { threshold: 0.15 });

    elements.forEach(function (el) { observer.observe(el); });
  }

  initReveal();
  document.body.addEventListener("htmx:afterSwap", initReveal);
})();
