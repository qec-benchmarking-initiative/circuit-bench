(() => {
  "use strict";

  document.querySelectorAll("[data-plot-axis-picker]").forEach((picker) => {
    const dialog = picker.querySelector("[data-plot-axis-dialog]");
    const opener = picker.querySelector("[data-plot-axis-open]");
    const select = picker.querySelector("[data-plot-axis-input]");
    const summary = picker.querySelector("[data-plot-axis-summary]");
    const search = picker.querySelector("[data-plot-axis-search]");
    const options = [...picker.querySelectorAll("[data-plot-axis-option]")];
    const empty = picker.querySelector("[data-plot-axis-empty]");
    let workingValue = select.value;

    const selectedOption = () => options.find(
      (option) => option.dataset.plotAxisOption === workingValue
    );

    const renderSelection = () => {
      options.forEach((option) => {
        option.setAttribute(
          "aria-pressed",
          String(option.dataset.plotAxisOption === workingValue),
        );
      });
    };

    const filterOptions = () => {
      const query = search.value.trim().toLowerCase();
      let visible = 0;
      options.forEach((option) => {
        const matches = !query || option.dataset.optionSearch.includes(query);
        option.hidden = !matches;
        if (matches) visible += 1;
      });
      empty.hidden = visible > 0;
    };

    const close = () => {
      dialog.close();
      opener.setAttribute("aria-expanded", "false");
    };

    opener.addEventListener("click", () => {
      workingValue = select.value;
      search.value = "";
      renderSelection();
      filterOptions();
      dialog.showModal();
      opener.setAttribute("aria-expanded", "true");
      search.focus();
    });

    options.forEach((option) => {
      option.addEventListener("click", () => {
        workingValue = option.dataset.plotAxisOption;
        renderSelection();
      });
    });

    search.addEventListener("input", filterOptions);
    picker.querySelectorAll("[data-plot-axis-cancel]").forEach((button) => {
      button.addEventListener("click", close);
    });
    picker.querySelector("[data-plot-axis-apply]").addEventListener("click", () => {
      if (workingValue === select.value) {
        close();
        return;
      }
      select.value = workingValue;
      summary.textContent = selectedOption()?.querySelector("span")?.textContent.trim();
      close();
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      close();
    });
    picker.dataset.enhanced = "true";
  });

  document.querySelectorAll("[data-plot-toggle]").forEach((toggle) => {
    const cell = toggle.closest("[data-plot-toggle-cell]");
    const label = cell.querySelector("[data-plot-toggle-label]");
    toggle.addEventListener("change", () => {
      cell.classList.toggle("is-enabled", toggle.checked);
      label.textContent = toggle.checked ? "Shown" : "Hidden";
    });
  });
})();
