(() => {
  "use strict";

  const themes = [
    ["reference-blue", "Reference blue"],
    ["burnt-orange", "Burnt orange"],
    ["oxide-red", "Oxide red"],
    ["moss", "Moss"],
    ["aubergine", "Aubergine dark"],
    ["graphite", "Graphite dark"],
    ["sepia", "Sepia"],
  ];
  const storageKey = "circuit-bench-theme";
  const themeNames = new Map(themes);
  const root = document.documentElement;

  const readStoredTheme = () => {
    try {
      const stored = window.localStorage.getItem(storageKey);
      return themeNames.has(stored) ? stored : themes[0][0];
    } catch (_error) {
      return themes[0][0];
    }
  };

  const applyTheme = (theme) => {
    root.dataset.theme = theme;
    try {
      window.localStorage.setItem(storageKey, theme);
    } catch (_error) {
      // The visual preference still works when browser storage is unavailable.
    }
  };

  applyTheme(readStoredTheme());

  document.addEventListener("DOMContentLoaded", () => {
    const switcher = document.querySelector("[data-theme-switcher]");
    if (!switcher) return;

    const swatches = [...switcher.querySelectorAll("[data-theme-swatch]")];
    const updateControl = () => {
      const current = root.dataset.theme;
      swatches.forEach((swatch) => {
        swatch.classList.toggle("is-current", swatch.dataset.themeSwatch === current);
      });
      switcher.title = `Theme: ${themeNames.get(current)}. Click for next theme.`;
    };

    updateControl();
    switcher.addEventListener("click", () => {
      const currentIndex = themes.findIndex(([key]) => key === root.dataset.theme);
      const nextTheme = themes[(currentIndex + 1) % themes.length][0];
      applyTheme(nextTheme);
      updateControl();
    });
  });
})();
