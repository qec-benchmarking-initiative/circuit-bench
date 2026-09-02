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

    if (checkbox.dataset.url) {
      const info = document.createElement("a");
      info.className = "tag-info-link";
      info.href = checkbox.dataset.url;
      info.setAttribute("aria-label", `Information about ${checkbox.dataset.label}`);
      info.title = `Information about ${checkbox.dataset.label}`;
      info.textContent = "i";
      tag.append(info);
    }

    const remove = document.createElement("button");
    remove.type = "button";
    remove.dataset.tagRemove = checkbox.value;
    remove.setAttribute("aria-label", `Remove ${checkbox.dataset.label}`);
    remove.textContent = "×";
    tag.append(remove);
    return tag;
  };

  const renderSelectedTags = (container, selected, emptyText) => {
    if (!container) return;
    container.replaceChildren();
    selected.forEach((checkbox) => container.append(makeSelectedTag(checkbox)));
    if (!selected.length) {
      const empty = document.createElement("span");
      empty.className = "muted";
      empty.textContent = emptyText;
      container.append(empty);
    }
  };

  const currentTagNamespace = (picker) => picker.dataset.tagNamespace
    || picker.querySelector("[data-tag-namespace-select]")?.value
    || "";

  const aliasEntries = (choice) => [...choice.querySelectorAll("[data-tag-alias]")]
    .map((item) => ({
      normalized: item.dataset.tagAlias,
      display: item.dataset.tagAliasDisplay,
    }));

  const updateTagPicker = (picker) => {
    const search = picker.querySelector("[data-tag-search]");
    const proposedLabel = (search?.value || "").trim().replace(/\s+/g, " ");
    const query = proposedLabel.toLocaleLowerCase();
    const namespace = currentTagNamespace(picker);
    const choices = [...picker.querySelectorAll("[data-tag-choice]")];
    const selected = choices
      .map((choice) => choice.querySelector('input[type="checkbox"]'))
      .filter((checkbox) => checkbox?.checked);

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
    let exactMatch = false;
    choices.forEach((choice) => {
      const checkbox = choice.querySelector('input[type="checkbox"]');
      const inNamespace = !namespace || choice.dataset.tagNamespace === namespace;
      const aliases = aliasEntries(choice);
      const aliasMatch = query
        ? aliases.find((alias) => alias.normalized.includes(query))
        : null;
      const matches = !query
        || choice.dataset.tagLabel.includes(query)
        || Boolean(aliasMatch);
      if (query && inNamespace) {
        exactMatch ||= choice.dataset.tagLabel === query
          || aliases.some((alias) => alias.normalized === query);
      }
      const aliasLabel = choice.querySelector("[data-tag-alias-match]");
      if (aliasLabel) {
        aliasLabel.textContent = aliasMatch ? `(${aliasMatch.display})` : "";
      }
      choice.hidden = !inNamespace || Boolean(checkbox?.checked) || !matches;
      if (!choice.hidden) visibleCount += 1;
    });

    const noResults = picker.querySelector("[data-tag-no-results]");
    if (noResults) {
      noResults.classList.toggle("hidden", visibleCount > 0);
      noResults.textContent = !query && selected.length === choices.length
        ? "All available tags are selected."
        : "No matching tags.";
    }
    picker.querySelectorAll("[data-tag-apply]").forEach((button) => {
      button.disabled = (
        button.dataset.tagApply !== "selection" && selected.length === 0
      );
    });
    const createSection = picker.querySelector("[data-tag-create-section]");
    if (createSection) {
      const eligible = Boolean(query) && !exactMatch;
      const description = picker.querySelector("[data-tag-create-description]");
      const aliases = picker.querySelector("[data-tag-create-aliases]");
      const status = picker.querySelector("[data-tag-create-status]");
      const proposal = picker.querySelector("[data-tag-proposed-label]");
      const concept = picker.querySelector("[data-tag-concept]");
      createSection.classList.toggle("is-disabled", !eligible);
      createSection.setAttribute("aria-disabled", String(!eligible));
      description.disabled = !eligible;
      aliases.disabled = !eligible;
      proposal.textContent = proposedLabel || "—";
      concept.textContent = {
        algorithm: "algorithm",
        code: "code",
        experiment: "circuit experiment",
      }[namespace] || "scientific";
      const hasDescription = Boolean(description.value.trim());
      picker.querySelectorAll("[data-tag-create]").forEach((button) => {
        button.disabled = !eligible || !hasDescription;
      });
      if (!query) {
        status.textContent = "Type a proposed tag name above.";
      } else if (exactMatch) {
        status.textContent = "That name already exactly matches a tag or alias.";
      } else if (!hasDescription) {
        status.textContent = "Add a description to create this tag.";
      } else if (status.dataset.error !== "true") {
        status.textContent = "This will create an immediately usable custom tag.";
      }
    }
    picker.dispatchEvent(new CustomEvent("filtergrid:tags-changed", {
      bubbles: true,
    }));
  };

  const csrfToken = () => document.querySelector(
    'input[name="csrfmiddlewaretoken"]'
  )?.value || document.cookie.split("; ")
    .find((part) => part.startsWith("csrftoken="))
    ?.split("=")[1] || "";

  const appendCreatedChoice = (picker, record) => {
    const choice = document.createElement("div");
    choice.className = `tag-choice tag-choice-${record.status}`;
    choice.dataset.tagChoice = "";
    choice.dataset.tagLabel = record.label.toLocaleLowerCase();
    choice.dataset.tagLabelDisplay = record.label;
    choice.dataset.tagStatus = record.status;
    choice.dataset.tagNamespace = record.namespace;

    const main = document.createElement("label");
    main.className = "tag-choice-main";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = picker.querySelector('[data-tag-choice] input')?.name || "tag";
    checkbox.value = record.id;
    checkbox.dataset.label = record.label;
    checkbox.dataset.status = record.status;
    checkbox.dataset.color = record.display_color || "";
    checkbox.dataset.url = record.url;
    checkbox.checked = true;
    const content = document.createElement("span");
    content.className = "tag-choice-content";
    const glyph = document.createElement("span");
    glyph.className = "tag-glyph";
    glyph.setAttribute("aria-hidden", "true");
    glyph.textContent = "◇";
    const aliasMatch = document.createElement("span");
    aliasMatch.className = "tag-choice-alias";
    aliasMatch.dataset.tagAliasMatch = "";
    content.append(glyph, document.createTextNode(` ${record.label} `), aliasMatch);
    main.append(checkbox, content);

    const info = document.createElement("a");
    info.className = "tag-info-link";
    info.href = record.url;
    info.setAttribute("aria-label", `Information about ${record.label}`);
    info.title = `Information about ${record.label}`;
    info.textContent = "i";
    const aliasData = document.createElement("span");
    aliasData.hidden = true;
    aliasData.dataset.tagAliases = "";
    record.aliases.forEach((alias) => {
      const item = document.createElement("span");
      item.dataset.tagAlias = alias.toLocaleLowerCase();
      item.dataset.tagAliasDisplay = alias;
      aliasData.append(item);
    });
    choice.append(main, info, aliasData);
    picker.querySelector("[data-tag-options]").append(choice);
    return checkbox;
  };

  const createTag = async (picker) => {
    const status = picker.querySelector("[data-tag-create-status]");
    const button = picker.querySelector("[data-tag-create]:not([hidden])");
    if (!picker.dataset.tagCreateUrl || button?.disabled) return;
    const payload = new URLSearchParams({
      namespace: currentTagNamespace(picker),
      label: picker.querySelector("[data-tag-search]").value.trim(),
      description: picker.querySelector("[data-tag-create-description]").value.trim(),
      aliases: picker.querySelector("[data-tag-create-aliases]").value,
    });
    picker.querySelectorAll("[data-tag-create]").forEach((item) => {
      item.disabled = true;
    });
    status.dataset.error = "false";
    status.textContent = "Creating tag…";
    try {
      const response = await fetch(picker.dataset.tagCreateUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-CSRFToken": csrfToken(),
        },
        body: payload,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The tag could not be created.");
      if (picker.dataset.tagCreatedRedirect === "true") {
        window.location.assign(data.tag.url);
        return;
      }
      appendCreatedChoice(picker, data.tag);
      picker.querySelector("[data-tag-search]").value = "";
      picker.querySelector("[data-tag-create-description]").value = "";
      picker.querySelector("[data-tag-create-aliases]").value = "";
      updateTagPicker(picker);
      status.textContent = `Created and selected “${data.tag.label}”.`;
    } catch (error) {
      status.dataset.error = "true";
      status.textContent = error.message;
      updateTagPicker(picker);
    }
  };

  document.querySelectorAll("[data-tag-picker]").forEach((picker) => {
    const dialog = picker.querySelector("[data-tag-dialog]");
    const search = picker.querySelector("[data-tag-search]");
    let selectionSnapshot = new Set();
    const matchInput = picker.querySelector("[data-tag-match-input]");
    let matchSnapshot = "all";

    const restoreSnapshot = () => {
      picker.querySelectorAll("[data-tag-choice] input").forEach((checkbox) => {
        checkbox.checked = selectionSnapshot.has(checkbox.value);
      });
      if (matchInput) matchInput.value = matchSnapshot;
      search.value = "";
      updateTagPicker(picker);
    };

    picker.querySelector("[data-tag-dialog-open]")?.addEventListener("click", () => {
      selectionSnapshot = new Set(
        [...picker.querySelectorAll("[data-tag-choice] input:checked")]
          .map((checkbox) => checkbox.value)
      );
      matchSnapshot = matchInput?.value || "all";
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
        const checkbox = [...picker.querySelectorAll("[data-tag-choice] input")].find(
          (candidate) => candidate.value === remove.dataset.tagRemove
        );
        if (checkbox) checkbox.checked = false;
        updateTagPicker(picker);
        if (!dialog?.open) {
          picker.dispatchEvent(new CustomEvent("filterquery:change", {
            bubbles: true,
          }));
        }
      }
      if (event.target.closest("[data-tag-create]")) createTag(picker);
    });
    const updateAfterCreateInput = () => {
      const status = picker.querySelector("[data-tag-create-status]");
      if (status) status.dataset.error = "false";
      updateTagPicker(picker);
    };
    search.addEventListener("input", updateAfterCreateInput);
    picker.querySelector("[data-tag-create-description]")?.addEventListener(
      "input", updateAfterCreateInput
    );
    picker.querySelector("[data-tag-create-aliases]")?.addEventListener(
      "input", updateAfterCreateInput
    );
    picker.querySelector("[data-tag-namespace-select]")?.addEventListener(
      "change", updateAfterCreateInput
    );

    picker.querySelectorAll("[data-tag-cancel]").forEach((button) => {
      button.addEventListener("click", () => {
        restoreSnapshot();
        dialog?.close();
      });
    });
    picker.querySelectorAll("[data-tag-apply]").forEach((button) => {
      button.addEventListener("click", () => {
        if (matchInput) matchInput.value = button.dataset.tagApply;
        search.value = "";
        updateTagPicker(picker);
        dialog?.close();
        picker.dispatchEvent(new CustomEvent("filterquery:change", {
          bubbles: true,
        }));
      });
    });
    dialog?.addEventListener("cancel", (event) => {
      event.preventDefault();
      restoreSnapshot();
      dialog.close();
    });

    updateTagPicker(picker);
  });
})();
