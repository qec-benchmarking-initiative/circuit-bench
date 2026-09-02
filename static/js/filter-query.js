(() => {
  "use strict";

  const forms = [...document.querySelectorAll("form")].filter(
    (form) => !form.matches("[data-plot-controls]")
      && form.querySelector("[data-filter-grid]")
  );
  if (!forms.length) return;

  const autoqueryKey = "circuitBench.filters.autoquery";
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
      form.requestSubmit();
    }, 140));
  };

  forms.forEach((form) => {
    form.addEventListener("control:commit", () => submitAutomatically(form));
    form.querySelector("[data-autoquery-toggle]")?.addEventListener("change", (event) => {
      autoqueryEnabled = event.target.checked;
      writeStorage(localStorage, autoqueryKey, String(autoqueryEnabled));
      syncControls();
      if (autoqueryEnabled) submitAutomatically(form);
    });
  });

  syncControls();
})();
