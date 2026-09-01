(() => {
  "use strict";

  const DISCLOSURE_KEY_PREFIX = "circuitBench.ui.disclosures:";
  const NAVIGATION_KEY_PREFIX = "circuitBench.ui.navigation:";
  const NAVIGATION_MAX_AGE_MS = 15000;
  const path = window.location.pathname;
  const disclosureKey = `${DISCLOSURE_KEY_PREFIX}${path}`;
  const navigationKey = `${NAVIGATION_KEY_PREFIX}${path}`;

  const readStorage = (key) => {
    try {
      return sessionStorage.getItem(key);
    } catch (_error) {
      return null;
    }
  };

  const writeStorage = (key, value) => {
    try {
      sessionStorage.setItem(key, value);
    } catch (_error) {
      // UI state is a convenience; navigation remains functional without it.
    }
  };

  const removeStorage = (key) => {
    try {
      sessionStorage.removeItem(key);
    } catch (_error) {
      // A stale state record is harmless when storage is unavailable.
    }
  };

  const disclosures = () => [
    ...document.querySelectorAll("details[id], details[data-ui-state-key]"),
  ];
  const disclosureIdentity = (details) => details.dataset.uiStateKey || details.id;

  const saveDisclosures = () => {
    const state = Object.fromEntries(
      disclosures()
        .map((details) => [disclosureIdentity(details), details.open])
        .filter(([identity]) => identity),
    );
    writeStorage(disclosureKey, JSON.stringify(state));
  };

  const restoreDisclosures = () => {
    const raw = readStorage(disclosureKey);
    if (!raw) return;
    try {
      const state = JSON.parse(raw);
      disclosures().forEach((details) => {
        const identity = disclosureIdentity(details);
        if (identity && typeof state[identity] === "boolean") {
          details.open = state[identity];
        }
      });
    } catch (_error) {
      removeStorage(disclosureKey);
    }
  };

  const saveNavigationState = () => {
    saveDisclosures();
    writeStorage(navigationKey, JSON.stringify({
      savedAt: Date.now(),
      scrollX: window.scrollX,
      scrollY: window.scrollY,
    }));
  };

  const restoreNavigationState = () => {
    const raw = readStorage(navigationKey);
    if (!raw) return;
    removeStorage(navigationKey);
    try {
      const state = JSON.parse(raw);
      if (Date.now() - state.savedAt > NAVIGATION_MAX_AGE_MS) return;
      const restore = () => window.scrollTo(state.scrollX, state.scrollY);
      requestAnimationFrame(() => {
        restore();
        requestAnimationFrame(restore);
        window.setTimeout(restore, 60);
      });
    } catch (_error) {
      // Invalid or stale navigation state must never block the page.
    }
  };

  try {
    history.scrollRestoration = "manual";
  } catch (_error) {
    // Some embedded browsers do not expose scroll restoration control.
  }
  restoreDisclosures();
  document.addEventListener("toggle", (event) => {
    if (event.target.matches("details[id], details[data-ui-state-key]")) {
      saveDisclosures();
    }
  }, true);
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form instanceof HTMLFormElement && form.method.toLowerCase() === "get") {
      saveNavigationState();
    }
  }, true);
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-ui-preserve-navigation], [data-filter-reset]")) {
      saveNavigationState();
    }
  }, true);

  if (document.readyState === "complete") {
    restoreNavigationState();
  } else {
    window.addEventListener("load", restoreNavigationState, { once: true });
  }
})();
