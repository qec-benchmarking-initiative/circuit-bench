(() => {
  "use strict";

  const forms = [...document.querySelectorAll("form")].filter(
    (form) => form.querySelector("[data-filter-grid]")
  );
  if (!forms.length) return;

  const autoqueryKey = "circuitBench.filters.autoquery";
  const disclosureKey = `circuitBench.filters.disclosures:${window.location.pathname}`;
  const navigationKey = "circuitBench.filters.navigation";
  const submitTimers = new WeakMap();

  const readStorage = (storage, key, fallback = null) => {
    try {
      const value = storage.getItem(key);
      return value === null ? fallback : value;
    } catch (_error) {
      return fallback;
    }
  };

  const writeStorage = (storage, key, value) => {
    try {
      storage.setItem(key, value);
    } catch (_error) {
      // Filters remain fully usable when storage is unavailable.
    }
  };

  const removeStorage = (storage, key) => {
    try {
      storage.removeItem(key);
    } catch (_error) {
      // Nothing needs recovery when storage is unavailable.
    }
  };

  const disclosureState = () => Object.fromEntries(
    [...document.querySelectorAll("details[data-filter-grid][id]")].map(
      (details) => [details.id, details.open]
    )
  );

  const saveDisclosures = () => {
    writeStorage(sessionStorage, disclosureKey, JSON.stringify(disclosureState()));
  };

  const restoreDisclosures = () => {
    const raw = readStorage(sessionStorage, disclosureKey);
    if (!raw) return;
    try {
      const state = JSON.parse(raw);
      document.querySelectorAll("details[data-filter-grid][id]").forEach((details) => {
        if (typeof state[details.id] === "boolean") details.open = state[details.id];
      });
    } catch (_error) {
      removeStorage(sessionStorage, disclosureKey);
    }
  };

  const saveNavigationState = () => {
    saveDisclosures();
    writeStorage(sessionStorage, navigationKey, JSON.stringify({
      path: window.location.pathname,
      savedAt: Date.now(),
      scrollX: window.scrollX,
      scrollY: window.scrollY,
    }));
  };

  const restoreNavigationState = () => {
    const raw = readStorage(sessionStorage, navigationKey);
    if (!raw) return;
    removeStorage(sessionStorage, navigationKey);
    try {
      const state = JSON.parse(raw);
      if (
        state.path !== window.location.pathname
        || Date.now() - state.savedAt > 15000
      ) return;
      const restore = () => window.scrollTo(state.scrollX, state.scrollY);
      requestAnimationFrame(() => {
        restore();
        requestAnimationFrame(restore);
        window.setTimeout(restore, 60);
      });
    } catch (_error) {
      // A stale navigation record should never block the page.
    }
  };

  try {
    history.scrollRestoration = "manual";
  } catch (_error) {
    // Some embedded browsers do not expose scroll restoration control.
  }
  restoreDisclosures();
  document.querySelectorAll("details[data-filter-grid][id]").forEach((details) => {
    details.addEventListener("toggle", saveDisclosures);
  });

  const storedAutoquery = readStorage(localStorage, autoqueryKey);
  let autoqueryEnabled = storedAutoquery === null ? true : storedAutoquery === "true";

  const syncControls = () => {
    forms.forEach((form) => {
      const toggle = form.querySelector("[data-autoquery-toggle]");
      const apply = form.querySelector("[data-filter-apply]");
      if (toggle) toggle.checked = autoqueryEnabled;
      if (!apply) return;
      apply.disabled = autoqueryEnabled;
      apply.textContent = autoqueryEnabled
        ? "Autoquery enabled"
        : apply.dataset.manualLabel;
    });
  };

  const submitAutomatically = (form) => {
    if (!autoqueryEnabled) return;
    window.clearTimeout(submitTimers.get(form));
    submitTimers.set(form, window.setTimeout(() => {
      saveNavigationState();
      form.requestSubmit();
    }, 140));
  };

  forms.forEach((form) => {
    form.addEventListener("submit", saveNavigationState);
    form.addEventListener("filterquery:change", () => submitAutomatically(form));
    form.querySelector("[data-autoquery-toggle]")?.addEventListener("change", (event) => {
      autoqueryEnabled = event.target.checked;
      writeStorage(localStorage, autoqueryKey, String(autoqueryEnabled));
      syncControls();
      if (autoqueryEnabled) submitAutomatically(form);
    });
    form.querySelector("[data-filter-reset]")?.addEventListener(
      "click",
      saveNavigationState
    );
  });

  syncControls();
  if (document.readyState === "complete") {
    restoreNavigationState();
  } else {
    window.addEventListener("load", restoreNavigationState, { once: true });
  }
})();
