(() => {
  "use strict";

  const parseSort = (value) => value.split(",").map((part) => part.trim()).filter(Boolean);
  const sortKey = (value) => value.startsWith("-") ? value.slice(1) : value;
  const toggled = (value) => value.startsWith("-") ? value.slice(1) : `-${value}`;
  const renderedSort = () => [...document.querySelectorAll("a[data-sort-index]")]
    .sort((a, b) => Number(a.dataset.sortIndex) - Number(b.dataset.sortIndex))
    .map((link) => link.dataset.sortDirection === "desc"
      ? `-${link.dataset.sortKey}`
      : link.dataset.sortKey);

  document.addEventListener("click", (event) => {
    const sortLink = event.target.closest("a[data-sort-key]");
    if (sortLink) {
      event.preventDefault();
      const url = new URL(window.location.href);
      const key = sortLink.dataset.sortKey;
      const encodedSort = parseSort(url.searchParams.get("sort") || "");
      const current = encodedSort.length ? encodedSort : renderedSort();
      let next;
      if (event.shiftKey) {
        const existingIndex = current.findIndex((value) => sortKey(value) === key);
        next = [...current];
        if (existingIndex >= 0) {
          next[existingIndex] = toggled(next[existingIndex]);
        } else {
          next.push(key);
        }
      } else if (current.length && sortKey(current[0]) === key) {
        next = [toggled(current[0])];
      } else {
        next = [key];
      }
      url.searchParams.set("sort", next.join(","));
      url.searchParams.delete("page");
      ["odata", "last_odata", "$filter", "$orderby", "$select", "$top", "$skip", "$count"]
        .forEach((name) => url.searchParams.delete(name));
      window.location.assign(url);
      return;
    }

    const opener = event.target.closest("[data-column-dialog-open]");
    if (opener) {
      document.getElementById(opener.dataset.columnDialogOpen)?.showModal();
    }
  });

  document.querySelectorAll("[data-column-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const checked = [...form.querySelectorAll('input[name="column"]:checked')]
        .map((input) => input.value);
      if (!checked.length) return;
      const url = new URL(window.location.href);
      url.searchParams.set("columns", checked.join(","));
      url.searchParams.delete("page");
      window.location.assign(url);
    });
    form.querySelector("[data-column-reset]")?.addEventListener("click", () => {
      const url = new URL(window.location.href);
      url.searchParams.delete("columns");
      url.searchParams.delete("page");
      window.location.assign(url);
    });
  });

  const makeSelectedTag = (checkbox) => {
    const tag = document.createElement("span");
    tag.className = `selected-tag selected-tag-${checkbox.dataset.status}`;
    tag.dataset.selectedTag = checkbox.value;
    if (checkbox.dataset.status === "official" && checkbox.dataset.color) {
      tag.style.setProperty("--tag-color", checkbox.dataset.color);
    }

    const icon = document.createElement("span");
    icon.className = "tag-glyph";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = checkbox.dataset.status === "official" ? "◆" : "◇";
    tag.append(icon, document.createTextNode(` ${checkbox.dataset.label} `));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.dataset.tagRemove = checkbox.value;
    remove.setAttribute("aria-label", `Remove ${checkbox.dataset.label}`);
    remove.textContent = "×";
    tag.append(remove);
    return tag;
  };

  const renderSelectedTags = (container, selected, emptyText) => {
    container.replaceChildren();
    selected.forEach((checkbox) => container.append(makeSelectedTag(checkbox)));
    if (!selected.length) {
      const empty = document.createElement("span");
      empty.className = "muted";
      empty.textContent = emptyText;
      container.append(empty);
    }
  };

  const updateTagPicker = (picker) => {
    const search = picker.querySelector("[data-tag-search]");
    const query = (search?.value || "").trim().toLocaleLowerCase();
    const choices = [...picker.querySelectorAll("[data-tag-choice]")];
    const selected = choices
      .map((choice) => choice.querySelector('input[type="checkbox"]'))
      .filter((checkbox) => checkbox.checked);

    renderSelectedTags(
      picker.querySelector("[data-tag-summary]"),
      selected,
      "No tags selected"
    );
    renderSelectedTags(
      picker.querySelector("[data-tag-selected-area]"),
      selected,
      "No tags selected."
    );

    let visibleCount = 0;
    choices.forEach((choice) => {
      const checkbox = choice.querySelector('input[type="checkbox"]');
      const matches = !query || choice.dataset.tagLabel.includes(query);
      choice.hidden = checkbox.checked || !matches;
      if (!choice.hidden) visibleCount += 1;
    });

    const noResults = picker.querySelector("[data-tag-no-results]");
    noResults.classList.toggle("hidden", visibleCount > 0);
    noResults.textContent = !query && selected.length === choices.length
      ? "All available tags are selected."
      : "No matching tags.";
    picker.querySelectorAll("[data-tag-apply]").forEach((button) => {
      button.disabled = selected.length === 0;
    });
    picker.dispatchEvent(new CustomEvent("filtergrid:tags-changed", {
      bubbles: true,
    }));
  };

  document.querySelectorAll("[data-tag-picker]").forEach((picker) => {
    const dialog = picker.querySelector("[data-tag-dialog]");
    const choices = [...picker.querySelectorAll("[data-tag-choice] input")];
    const search = picker.querySelector("[data-tag-search]");
    let selectionSnapshot = [];
    const matchInput = picker.querySelector("[data-tag-match-input]");
    let matchSnapshot = "all";

    const restoreSnapshot = () => {
      choices.forEach((checkbox, index) => {
        checkbox.checked = selectionSnapshot[index];
      });
      matchInput.value = matchSnapshot;
      search.value = "";
      updateTagPicker(picker);
    };

    picker.querySelector("[data-tag-dialog-open]").addEventListener("click", () => {
      selectionSnapshot = choices.map((checkbox) => checkbox.checked);
      matchSnapshot = matchInput.value || "all";
      search.value = "";
      updateTagPicker(picker);
      dialog.showModal();
      search.focus();
    });

    picker.addEventListener("change", (event) => {
      if (event.target.matches('[data-tag-choice] input[type="checkbox"]')) {
        updateTagPicker(picker);
      }
    });
    picker.addEventListener("click", (event) => {
      const remove = event.target.closest("[data-tag-remove]");
      if (remove) {
        const checkbox = choices.find(
          (candidate) => candidate.value === remove.dataset.tagRemove
        );
        if (checkbox) checkbox.checked = false;
        updateTagPicker(picker);
        if (!dialog.open) {
          picker.dispatchEvent(new CustomEvent("filterquery:change", {
            bubbles: true,
          }));
        }
      }
    });
    search.addEventListener("input", () => updateTagPicker(picker));

    picker.querySelectorAll("[data-tag-cancel]").forEach((button) => {
      button.addEventListener("click", () => {
        restoreSnapshot();
        dialog.close();
      });
    });
    picker.querySelectorAll("[data-tag-apply]").forEach((button) => {
      button.addEventListener("click", () => {
        matchInput.value = button.dataset.tagApply;
        search.value = "";
        updateTagPicker(picker);
        dialog.close();
        picker.dispatchEvent(new CustomEvent("filterquery:change", {
          bubbles: true,
        }));
      });
    });
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      restoreSnapshot();
      dialog.close();
    });

    updateTagPicker(picker);
  });
})();
