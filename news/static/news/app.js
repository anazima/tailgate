(function () {
  "use strict";

  const toast = document.getElementById("toast");
  let toastTimer = null;
  function showToast(text) {
    toast.textContent = text;
    toast.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.add("hidden"), 1500);
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } finally { ta.remove(); }
    return Promise.resolve();
  }

  const lightbox = document.getElementById("lightbox");
  const lightboxImg = document.getElementById("lightbox-img");

  const menuBtn = document.getElementById("menu-btn");
  const menu = document.getElementById("menu");
  const filtersBtn = document.getElementById("filters-btn");
  const filters = document.getElementById("filters");

  document.addEventListener("click", (event) => {
    if (menuBtn && menuBtn.contains(event.target)) {
      const open = menu.classList.toggle("hidden") === false;
      menuBtn.setAttribute("aria-expanded", String(open));
      return;
    }
    if (menu && !menu.classList.contains("hidden") && !menu.contains(event.target)) {
      menu.classList.add("hidden");
      menuBtn.setAttribute("aria-expanded", "false");
    }
    if (filtersBtn && filtersBtn.contains(event.target)) {
      filters.classList.toggle("hidden");
      return;
    }
    const copyBtn = event.target.closest("[data-copy]");
    if (copyBtn) {
      copyText(copyBtn.dataset.copy).then(() => showToast("Copied"), () => showToast("Copy failed"));
      return;
    }
    const img = event.target.closest("[data-lightbox]");
    if (img) {
      lightboxImg.src = img.dataset.lightbox;
      lightbox.showModal();
      return;
    }
    if (event.target === lightbox || event.target === lightboxImg) {
      lightbox.close();
    }
  });
})();
