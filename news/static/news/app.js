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

  // --- Browser push notifications ---
  const pushToggle = document.getElementById("push-toggle");
  const pushTest = document.getElementById("push-test");
  const vapidKey = document.body.dataset.vapid;
  const csrf = document.body.dataset.csrf;
  const pushSupported = "serviceWorker" in navigator && "PushManager" in window && !!vapidKey;

  function urlBase64ToUint8Array(base64) {
    const padding = "=".repeat((4 - (base64.length % 4)) % 4);
    const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }

  function postJson(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: JSON.stringify(body) });
  }

  async function currentSubscription() {
    const reg = await navigator.serviceWorker.register("/sw.js");
    return { reg, sub: await reg.pushManager.getSubscription() };
  }

  function renderPushState(enabled) {
    if (!pushToggle) return;
    pushToggle.textContent = enabled ? "Disable notifications" : "Enable notifications";
    pushToggle.dataset.state = enabled ? "on" : "off";
    pushTest.classList.toggle("hidden", !enabled);
  }

  async function enablePush() {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") { showToast("Notifications blocked in browser settings"); return; }
    const { reg } = await currentSubscription();
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(vapidKey) });
    const res = await postJson("/push/subscribe/", sub.toJSON());
    if (!res.ok) throw new Error("subscribe failed");
    renderPushState(true);
    showToast("Notifications enabled");
  }

  async function disablePush() {
    const { sub } = await currentSubscription();
    if (sub) { await postJson("/push/unsubscribe/", sub.toJSON()); await sub.unsubscribe(); }
    renderPushState(false);
    showToast("Notifications disabled");
  }

  if (pushToggle) {
    if (!pushSupported) {
      pushToggle.textContent = "Notifications not supported here";
      pushToggle.disabled = true;
    } else {
      currentSubscription().then(({ sub }) => renderPushState(!!sub)).catch(() => renderPushState(false));
      pushToggle.addEventListener("click", () => {
        const action = pushToggle.dataset.state === "on" ? disablePush() : enablePush();
        action.catch((err) => { console.error(err); showToast("Could not change notifications"); });
      });
      pushTest.addEventListener("click", async () => {
        const res = await fetch("/push/test/", { method: "POST", headers: { "X-CSRFToken": csrf } });
        showToast(await res.text());
      });
    }
  }

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
