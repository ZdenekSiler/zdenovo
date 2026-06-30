// Client-side table of contents for blog posts.
// Scans h2/h3 headings in .prose-custom, builds desktop + mobile TOC lists,
// and highlights the active heading on scroll via IntersectionObserver.
(function () {
  "use strict";

  var observer = null;

  function slugify(text) {
    return text
      .toLowerCase()
      .trim()
      .replace(/\s+/g, "-")
      .replace(/[^a-z0-9-]/g, "")
      .replace(/-+/g, "-");
  }

  function assignIds(headings) {
    var seen = {};
    headings.forEach(function (h) {
      var id = h.id;
      if (!id) {
        id = slugify(h.textContent);
      }
      if (seen[id]) {
        seen[id]++;
        id = id + "-" + seen[id];
      } else {
        seen[id] = 1;
      }
      h.id = id;
    });
  }

  // Builds a nested <ul> reflecting h2/h3 hierarchy. h3s nest under the
  // preceding h2; a leading h3 with no parent h2 renders flat.
  function buildList(headings) {
    var rootUl = document.createElement("ul");
    var currentSubUl = null;

    headings.forEach(function (h) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = "#" + h.id;
      a.textContent = h.textContent;
      a.dataset.tocTarget = h.id;
      li.appendChild(a);

      if (h.tagName === "H3") {
        li.classList.add("toc-sub");
        if (!currentSubUl) {
          rootUl.appendChild(li);
        } else {
          currentSubUl.appendChild(li);
        }
      } else {
        rootUl.appendChild(li);
        currentSubUl = null;
      }

      if (h.tagName === "H2") {
        var subUl = document.createElement("ul");
        subUl.className = "toc-sub-list";
        li.appendChild(subUl);
        currentSubUl = subUl;
      }
    });

    // Drop empty sub-lists left behind on h2s with no h3 children.
    rootUl.querySelectorAll(".toc-sub-list").forEach(function (ul) {
      if (!ul.children.length) ul.remove();
    });

    return rootUl;
  }

  function buildNav(headings) {
    var nav = document.createElement("nav");
    nav.id = "toc-nav";
    nav.setAttribute("aria-label", "Table of contents");
    nav.appendChild(buildList(headings));
    return nav;
  }

  function buildMobileAccordion(headings) {
    var details = document.createElement("details");
    details.className = "toc-accordion";

    var summary = document.createElement("summary");
    summary.textContent = "On this page";
    details.appendChild(summary);

    details.appendChild(buildNav(headings));
    return details;
  }

  function attachSmoothScroll(container) {
    container.querySelectorAll("a[data-toc-target]").forEach(function (a) {
      a.addEventListener("click", function (e) {
        var id = a.dataset.tocTarget;
        var target = document.getElementById(id);
        if (!target) return;
        e.preventDefault();
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        history.pushState(null, "", "#" + id);
      });
    });
  }

  function setActiveLink(id) {
    document.querySelectorAll("a[data-toc-target]").forEach(function (a) {
      if (a.dataset.tocTarget === id) {
        a.classList.add("toc-active");
      } else {
        a.classList.remove("toc-active");
      }
    });
  }

  function observeHeadings(headings) {
    if (observer) {
      observer.disconnect();
      observer = null;
    }

    observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          setActiveLink(entry.target.id);
        }
      });
    }, { threshold: 0.5 });

    headings.forEach(function (h) { observer.observe(h); });
  }

  function clearContainer(el) {
    if (!el) return;
    el.innerHTML = "";
  }

  function init() {
    if (observer) {
      observer.disconnect();
      observer = null;
    }

    var prose = document.querySelector(".prose-custom");
    var sidebarContainer = document.getElementById("toc-container");
    var mobileContainer = document.getElementById("toc-mobile");

    clearContainer(sidebarContainer);
    clearContainer(mobileContainer);

    if (!prose) return;

    var headings = Array.prototype.slice.call(prose.querySelectorAll("h2, h3"));
    if (headings.length < 3) return;

    assignIds(headings);

    if (sidebarContainer) {
      var desktopNav = buildNav(headings);
      sidebarContainer.appendChild(desktopNav);
      attachSmoothScroll(desktopNav);
    }

    if (mobileContainer) {
      var accordion = buildMobileAccordion(headings);
      mobileContainer.appendChild(accordion);
      attachSmoothScroll(accordion);
    }

    observeHeadings(headings);
  }

  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSwap", init);
})();
