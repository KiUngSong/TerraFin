document.addEventListener("DOMContentLoaded", () => {
  const headerTitle = document.querySelector(".md-header__title");
  const homeLink = document.querySelector(".md-header .md-logo");

  if (!headerTitle || !homeLink || !(homeLink instanceof HTMLAnchorElement)) {
    return;
  }

  const navigateHome = () => {
    window.location.assign(homeLink.href);
  };

  headerTitle.setAttribute("role", "link");
  headerTitle.setAttribute("tabindex", "0");
  headerTitle.setAttribute("aria-label", "Go to TerraFin Docs home");

  headerTitle.addEventListener("click", () => {
    navigateHome();
  });

  headerTitle.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }

    event.preventDefault();
    navigateHome();
  });
});
