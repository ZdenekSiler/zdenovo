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
