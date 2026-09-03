(() => {
  "use strict";

  const appendTagText = (container, label, status) => {
    const text = document.createElement("span");
    text.textContent = label;
    if (status === "retired") text.className = "tag-deleted-label";
    container.append(document.createTextNode(" "), text);
    if (status === "retired") {
      const note = document.createElement("span");
      note.className = "tag-deleted-note";
      note.textContent = "(Deleted)";
      container.append(document.createTextNode(" "), note);
    }
  };

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
    icon.textContent = "✓";
    tag.append(icon);
    appendTagText(tag, checkbox.dataset.label, checkbox.dataset.status);
    tag.append(document.createTextNode(" "));

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

  const parentEntries = (choice) => [...choice.querySelectorAll("[data-tag-parent]")]
    .map((item) => ({
      id: item.dataset.parentId,
      label: item.dataset.parentLabel,
      status: item.dataset.parentStatus,
      color: item.dataset.parentColor,
      url: item.dataset.parentUrl,
      namespace: item.dataset.parentNamespace,
    }));

  const choiceId = (choice) => {
    const checkbox = choice.querySelector('input[type="checkbox"]');
    return checkbox?.dataset.tagId || checkbox?.value || choice.dataset.tagId;
  };

  const makeContextParent = (record, root, choices) => {
    const card = document.createElement("div");
    card.className = `tag-choice tag-choice-${record.status} tag-context-parent`;
    if (record.status === "official" && record.color) {
      card.style.setProperty("--tag-color", record.color);
    }
    const targetChoice = choices.find((choice) => choiceId(choice) === record.id);
    const targetCheckbox = targetChoice?.querySelector('input[type="checkbox"]');
    const parentSelector = root.closest("[data-tag-parent-selector]");
    const picker = root.closest("[data-tag-picker]");
    const pickerNamespace = picker ? currentTagNamespace(picker) : "";
    const selectable = Boolean(targetCheckbox) && (
      Boolean(parentSelector)
      || !picker
      || !pickerNamespace
      || targetChoice.dataset.tagNamespace === pickerNamespace
    );
    const content = document.createElement(selectable ? "button" : "span");
    content.className = "tag-choice-main tag-choice-content";
    if (selectable) {
      content.type = "button";
      content.classList.add("tag-context-parent-action");
      content.setAttribute("aria-label", `Select ${record.label}`);
      content.addEventListener("click", () => {
        targetCheckbox.checked = true;
        targetCheckbox.dispatchEvent(new Event("change", { bubbles: true }));
      });
    }
    const glyph = document.createElement("span");
    glyph.className = "tag-glyph";
    glyph.setAttribute("aria-hidden", "true");
    glyph.textContent = record.status === "official" ? "◆" : "◇";
    content.append(glyph);
    appendTagText(content, record.label, record.status);
    card.append(content);
    if (record.url) {
      const info = document.createElement("a");
      info.className = "tag-info-link";
      info.href = record.url;
      info.setAttribute("aria-label", `Information about ${record.label}`);
      info.textContent = "i";
      card.append(info);
    }
    return card;
  };

  const renderContextParents = (root, choices, selectedIds, hasSearchQuery) => {
    const results = root?.querySelector("[data-tag-context-parent-results]");
    if (!results) return;
    const visibleIds = new Set(
      choices.filter((choice) => !choice.hidden).map(choiceId)
    );
    const records = new Map();
    choices.filter((choice) => {
      const checkbox = choice.querySelector('input[type="checkbox"]');
      return checkbox?.checked || (hasSearchQuery && !choice.hidden);
    }).forEach((choice) => {
      parentEntries(choice).forEach((record) => {
        if (!selectedIds.has(record.id) && !visibleIds.has(record.id)) {
          records.set(record.id, record);
        }
      });
    });
    results.replaceChildren(
      ...[...records.values()]
        .sort((a, b) => a.label.localeCompare(b.label))
        .map((record) => makeContextParent(record, root, choices))
    );
    root.hidden = records.size === 0;
  };

  const updateTagPicker = (picker) => {
    const search = picker.querySelector("[data-tag-search]");
    const proposedLabel = (search?.value || "").trim().replace(/\s+/g, " ");
    const query = proposedLabel.toLocaleLowerCase();
    const namespace = currentTagNamespace(picker);
    const choices = [...picker.querySelectorAll("[data-tag-choice]")];
    const selected = choices
      .map((choice) => choice.querySelector('input[type="checkbox"]'))
      .filter((checkbox) => checkbox?.checked);
    const selectedIds = new Set(selected.map((checkbox) => checkbox.dataset.tagId));

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
      choice.hidden = !inNamespace || (!checkbox?.checked && !matches);
      choice.classList.toggle("is-selected", Boolean(checkbox?.checked));
      const glyph = choice.querySelector(".tag-glyph");
      if (glyph) {
        glyph.textContent = checkbox?.checked
          ? "✓"
          : choice.dataset.tagStatus === "official" ? "◆" : "◇";
      }
      if (!choice.hidden) visibleCount += 1;
    });

    const noResults = picker.querySelector("[data-tag-no-results]");
    if (noResults) {
      noResults.classList.toggle("hidden", visibleCount > 0);
      noResults.textContent = "No matching tags.";
    }
    renderContextParents(
      picker.querySelector("[data-tag-context-parents]"),
      choices,
      selectedIds,
      Boolean(query)
    );
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
      const visibility = picker.querySelector("[data-tag-create-visibility]");
      const status = picker.querySelector("[data-tag-create-status]");
      const proposal = picker.querySelector("[data-tag-proposed-label]");
      const concept = picker.querySelector("[data-tag-concept]");
      createSection.classList.toggle("is-disabled", !eligible);
      createSection.setAttribute("aria-disabled", String(!eligible));
      description.disabled = !eligible;
      aliases.disabled = !eligible;
      visibility.disabled = !eligible;
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
      const parentSelector = createSection.querySelector("[data-tag-parent-selector]");
      parentSelector?.querySelectorAll("[data-tag-parent-toggle], [data-tag-parent-choice]")
        .forEach((control) => { control.disabled = !eligible; });
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
    picker.dispatchEvent(new CustomEvent("tagpicker:layoutchange", {
      bubbles: true,
    }));
  };

  const csrfToken = () => document.querySelector(
    'input[name="csrfmiddlewaretoken"]'
  )?.value || document.cookie.split("; ")
    .find((part) => part.startsWith("csrftoken="))
    ?.split("=")[1] || "";

  const cloneSelectionMap = (selection) => new Map(
    [...selection].map(([key, record]) => [key, { ...record }])
  );

  const recordFromSelectionInput = (input) => ({
    key: input.dataset.tagKey,
    source: input.dataset.tagSource,
    label: input.dataset.tagLabel,
    url: input.dataset.tagUrl,
    selectable: true,
    selected: true,
    status: input.dataset.tagStatus,
    colour: input.dataset.tagColour || "",
    namespace: input.closest("[data-tag-picker]")?.dataset.tagNamespace || "",
    aliases: [],
    database_id: input.dataset.tagDatabaseId || "",
    slug: input.dataset.tagSlug || "",
    source_suffix: input.dataset.tagSource === "ecz" ? "(ECZ)" : "",
  });

  const appendServerTagText = (container, record) => {
    appendTagText(container, record.label, record.status);
    if (record.source_suffix) {
      const suffix = document.createElement("span");
      suffix.className = "tag-source-suffix";
      suffix.textContent = ` ${record.source_suffix}`;
      container.append(suffix);
    }
    if (record.matched_alias) {
      const alias = document.createElement("span");
      alias.className = "tag-choice-alias";
      alias.textContent = ` (${record.matched_alias})`;
      container.append(alias);
    }
  };

  const makeServerSelectedTag = (record) => {
    const tag = document.createElement("span");
    tag.className = [
      "selected-tag",
      `selected-tag-${record.status}`,
      `selected-tag-source-${record.source}`,
    ].join(" ");
    tag.dataset.selectedTag = record.key;
    if (record.status === "official" && record.colour) {
      tag.style.setProperty("--tag-color", record.colour);
    }

    const glyph = document.createElement("span");
    glyph.className = "tag-glyph";
    glyph.setAttribute("aria-hidden", "true");
    glyph.textContent = "✓";
    tag.append(glyph);
    appendServerTagText(tag, record);

    if (record.url) {
      const info = document.createElement("a");
      info.className = "tag-info-link";
      info.href = record.url;
      info.setAttribute("aria-label", `Information about ${record.label}`);
      info.title = `Information about ${record.label}`;
      info.textContent = "i";
      tag.append(info);
    }

    const remove = document.createElement("button");
    remove.type = "button";
    remove.dataset.tagRemove = record.key;
    remove.setAttribute("aria-label", `Remove ${record.label}`);
    remove.textContent = "×";
    tag.append(remove);
    return tag;
  };

  const makeServerChoice = (record, selected, onToggle) => {
    const card = document.createElement("div");
    card.className = [
      "tag-choice",
      `tag-choice-${record.status}`,
      `tag-choice-source-${record.source}`,
      selected ? "is-selected" : "",
    ].filter(Boolean).join(" ");
    card.dataset.taxonomyKey = record.key;
    if (record.status === "official" && record.colour) {
      card.style.setProperty("--tag-color", record.colour);
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-choice-main tag-choice-content";
    button.disabled = !record.selectable && !selected;
    button.setAttribute(
      "aria-label",
      `${selected ? "Remove" : "Select"} ${record.label}`
    );
    button.setAttribute("aria-pressed", String(selected));
    const glyph = document.createElement("span");
    glyph.className = "tag-glyph";
    glyph.setAttribute("aria-hidden", "true");
    glyph.textContent = selected ? "✓" : record.status === "official" ? "◆" : "◇";
    button.append(glyph);
    appendServerTagText(button, record);
    button.addEventListener("click", () => onToggle(record));
    card.append(button);

    if (record.url) {
      const info = document.createElement("a");
      info.className = "tag-info-link";
      info.href = record.url;
      info.setAttribute("aria-label", `Information about ${record.label}`);
      info.title = `Information about ${record.label}`;
      info.textContent = "i";
      card.append(info);
    }
    return card;
  };

  const initServerTagPicker = (picker) => {
    const dialog = picker.querySelector("[data-tag-dialog]");
    const search = picker.querySelector("[data-tag-search]");
    const namespaceSelect = picker.querySelector("[data-tag-namespace-select]");
    const matchInput = picker.querySelector("[data-tag-match-input]");
    const selectionInputs = picker.querySelector("[data-tag-selection-inputs]");
    const mode = picker.dataset.mode || "filter";
    let selected = new Map(
      [...picker.querySelectorAll("[data-tag-selection]")]
        .map(recordFromSelectionInput)
        .map((record) => [record.key, record])
    );
    let selectionSnapshot = cloneSelectionMap(selected);
    let matchSnapshot = matchInput?.value || "all";
    let displayed = { circuit_bench: new Map(), ecz: new Map() };
    let parentDisplayed = { circuit_bench: new Map(), ecz: new Map() };
    let nextOffsets = { circuit_bench: null, ecz: null };
    let parentNextOffsets = { circuit_bench: null, ecz: null };
    let createParents = new Map();
    let createParentDisplayed = { circuit_bench: new Map(), ecz: new Map() };
    let requestController = null;
    let createParentRequestController = null;
    let requestSerial = 0;
    let createParentRequestSerial = 0;
    let searchTimer = null;
    let createParentSearchTimer = null;
    let createParentEligible = false;

    const namespace = () => currentTagNamespace(picker);
    const selectionValue = (record) => {
      if (mode === "submission") return record.database_id;
      if (namespace() === "code") return record.key;
      return record.slug || record.key;
    };
    const selectionName = (record) => (
      mode === "submission" && record.source === "ecz"
        ? picker.dataset.eczInputName
        : picker.dataset.nativeInputName
    );

    const syncSelectionInputs = () => {
      if (!selectionInputs) return;
      const fragment = document.createDocumentFragment();
      selected.forEach((record) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = selectionName(record);
        input.value = selectionValue(record);
        input.dataset.tagSelection = "";
        input.dataset.tagKey = record.key;
        input.dataset.tagSource = record.source;
        input.dataset.tagDatabaseId = record.database_id || "";
        input.dataset.tagSlug = record.slug || "";
        input.dataset.tagLabel = record.label;
        input.dataset.tagStatus = record.status;
        input.dataset.tagColour = record.colour || "";
        input.dataset.tagUrl = record.url || "";
        fragment.append(input);
      });
      selectionInputs.replaceChildren(fragment);
    };

    const renderSelected = () => {
      const records = [...selected.values()].sort((a, b) => (
        a.label.localeCompare(b.label) || a.key.localeCompare(b.key)
      ));
      [
        [picker.querySelector("[data-tag-summary]"), "No tags selected"],
        [picker.querySelector("[data-tag-selected-area]"), "No tags selected."],
        [picker.querySelector("[data-tag-create-parent-summary]"), "No parent tags selected"],
      ].forEach(([container, emptyText]) => {
        if (!container) return;
        container.replaceChildren(...records.map(makeServerSelectedTag));
        if (!records.length) {
          const empty = document.createElement("span");
          empty.className = container.matches("[data-tag-summary]")
            ? "tag-picker-empty-summary"
            : "muted";
          empty.textContent = emptyText;
          container.append(empty);
        }
      });
      syncSelectionInputs();
      picker.querySelectorAll("[data-tag-apply]").forEach((button) => {
        button.disabled = button.dataset.tagApply !== "selection" && !selected.size;
      });
    };

    const sourceLabel = (source) => source === "ecz"
      ? "Error Correction Zoo tags"
      : "Circuit Bench tags";

    const makeCreateParentChip = (record) => {
      const chip = makeServerSelectedTag(record);
      chip.dataset.selectedParent = record.key;
      delete chip.dataset.selectedTag;
      const remove = chip.querySelector("[data-tag-remove]");
      remove.dataset.tagCreateParentRemove = record.key;
      delete remove.dataset.tagRemove;
      remove.setAttribute("aria-label", `Remove ${record.label} as a parent`);
      return chip;
    };

    const renderCreateParentSource = (source) => {
      const container = picker.querySelector(
        `[data-tag-create-parent-results="${source}"]`
      );
      if (!container) return;
      const records = createParentDisplayed[source];
      container.replaceChildren(...[...records.values()].map((record) => (
        makeServerChoice(record, createParents.has(record.key), toggleCreateParent)
      )));
      const wrapper = container.closest("[data-tag-create-parent-source]");
      if (wrapper) wrapper.hidden = records.size === 0;
    };

    const renderCreateParents = () => {
      const selector = picker.querySelector("[data-tag-parent-selector]");
      if (!selector) return;
      const summary = selector.querySelector("[data-tag-parent-summary]");
      const records = [...createParents.values()].sort((a, b) => (
        a.label.localeCompare(b.label) || a.key.localeCompare(b.key)
      ));
      summary.replaceChildren(...records.map(makeCreateParentChip));
      if (!records.length) {
        const empty = document.createElement("span");
        empty.className = "tag-picker-empty-summary";
        empty.textContent = "No parent tags selected";
        summary.append(empty);
      }
      renderCreateParentSource("circuit_bench");
      renderCreateParentSource("ecz");
      const empty = !createParentDisplayed.circuit_bench.size
        && !createParentDisplayed.ecz.size;
      selector.querySelector("[data-tag-parent-no-results]")
        ?.classList.toggle("hidden", !empty);
    };

    const fetchCreateParentResults = async () => {
      if (!createParentEligible) return;
      const selector = picker.querySelector("[data-tag-parent-selector]");
      if (!selector) return;
      createParentRequestController?.abort();
      createParentRequestController = new AbortController();
      const serial = ++createParentRequestSerial;
      const parameters = new URLSearchParams({
        namespace: namespace(),
        q: selector.querySelector("[data-tag-parent-search]")?.value.trim() || "",
      });
      createParents.forEach((_record, key) => parameters.append("selected", key));
      try {
        const response = await fetch(
          `${picker.dataset.tagSearchUrl}?${parameters}`,
          {
            headers: { Accept: "application/json" },
            signal: createParentRequestController.signal,
          }
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Parent-tag search failed.");
        if (serial !== createParentRequestSerial) return;
        createParents = new Map(data.selected.map((record) => [record.key, record]));
        ["circuit_bench", "ecz"].forEach((source) => {
          createParentDisplayed[source] = new Map(
            data[source].shown.map((record) => [record.key, record])
          );
          const remainder = selector.querySelector(
            `[data-tag-create-parent-remaining="${source}"]`
          );
          if (remainder) {
            remainder.hidden = data[source].remaining === 0;
            remainder.textContent = `+ ${data[source].remaining} ${sourceLabel(source)}`;
          }
        });
        renderCreateParents();
      } catch (error) {
        if (error.name === "AbortError") return;
        const noResults = selector.querySelector("[data-tag-parent-no-results]");
        if (noResults) {
          noResults.textContent = error.message;
          noResults.classList.remove("hidden");
        }
      }
    };

    function toggleCreateParent(record) {
      if (!createParentEligible) return;
      if (createParents.has(record.key)) createParents.delete(record.key);
      else if (record.selectable) {
        createParents.set(record.key, { ...record, selected: true });
      }
      fetchCreateParentResults();
    }

    const renderSource = (source, records, parent = false) => {
      const selector = parent
        ? `[data-taxonomy-parent-results="${source}"]`
        : `[data-taxonomy-results="${source}"]`;
      const container = picker.querySelector(selector);
      if (!container) return;
      container.replaceChildren(...[...records.values()].map((record) => (
        makeServerChoice(record, selected.has(record.key), toggleRecord)
      )));
      const load = picker.querySelector(parent
        ? `[data-taxonomy-parent-load="${source}"]`
        : `[data-taxonomy-load="${source}"]`);
      const offset = parent ? parentNextOffsets[source] : nextOffsets[source];
      if (load) {
        load.hidden = offset === null;
        const remaining = Number(load.dataset.remaining || 0);
        load.textContent = `+ ${remaining} ${sourceLabel(source)}`;
      }
      const wrapper = container.closest("[data-taxonomy-source], [data-taxonomy-parent-source]");
      if (wrapper) wrapper.hidden = records.size === 0 && offset === null;
    };

    const renderResults = () => {
      renderSource("circuit_bench", displayed.circuit_bench);
      renderSource("ecz", displayed.ecz);
      renderSource("circuit_bench", parentDisplayed.circuit_bench, true);
      renderSource("ecz", parentDisplayed.ecz, true);
      const parentSection = picker.querySelector("[data-tag-context-parents]");
      if (parentSection) {
        parentSection.hidden = !parentDisplayed.circuit_bench.size
          && !parentDisplayed.ecz.size
          && parentNextOffsets.circuit_bench === null
          && parentNextOffsets.ecz === null;
      }
      const noResults = picker.querySelector("[data-tag-no-results]");
      if (noResults) {
        const empty = !displayed.circuit_bench.size && !displayed.ecz.size;
        noResults.classList.toggle("hidden", !empty);
      }
      renderSelected();
      updateCreateEligibility();
      picker.dispatchEvent(new CustomEvent("tagpicker:layoutchange", { bubbles: true }));
    };

    const addPage = (target, records, append) => {
      if (!append) target.clear();
      records.forEach((record) => target.set(record.key, record));
    };

    const queryParameters = (overrides = {}) => {
      const parameters = new URLSearchParams({
        namespace: namespace(),
        q: search?.value.trim() || "",
      });
      selected.forEach((_record, key) => parameters.append("selected", key));
      if (picker.dataset.tagExcludedKey) {
        parameters.append("exclude", picker.dataset.tagExcludedKey);
      }
      [...displayed.circuit_bench.keys(), ...displayed.ecz.keys()]
        .forEach((key) => parameters.append("context", key));
      Object.entries(overrides).forEach(([key, value]) => {
        if (value !== null && value !== undefined) parameters.set(key, value);
      });
      return parameters;
    };

    const fetchResults = async ({ source = null, parentSource = null } = {}) => {
      requestController?.abort();
      requestController = new AbortController();
      const serial = ++requestSerial;
      const overrides = {};
      if (source) overrides[`${source === "ecz" ? "ecz" : "cb"}_offset`] = (
        nextOffsets[source] || 0
      );
      if (parentSource) {
        overrides[`parent_${parentSource === "ecz" ? "ecz" : "cb"}_offset`] = (
          parentNextOffsets[parentSource] || 0
        );
      }
      picker.classList.add("is-loading");
      try {
        const response = await fetch(
          `${picker.dataset.tagSearchUrl}?${queryParameters(overrides)}`,
          { headers: { Accept: "application/json" }, signal: requestController.signal }
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Tag search failed.");
        if (serial !== requestSerial) return;
        selected = new Map(data.selected.map((record) => [record.key, record]));
        ["circuit_bench", "ecz"].forEach((itemSource) => {
          const page = data[itemSource];
          const append = source === itemSource;
          const updatePrincipal = (!source && !parentSource) || append;
          if (updatePrincipal) addPage(displayed[itemSource], page.shown, append);
          if (updatePrincipal) nextOffsets[itemSource] = page.next_offset;
          const load = picker.querySelector(`[data-taxonomy-load="${itemSource}"]`);
          if (load && updatePrincipal) load.dataset.remaining = page.remaining;

          const parentPage = data.unselected_parents[itemSource];
          const appendParent = parentSource === itemSource;
          if (!parentSource || appendParent) {
            addPage(parentDisplayed[itemSource], parentPage.shown, appendParent);
            parentNextOffsets[itemSource] = parentPage.next_offset;
            const parentLoad = picker.querySelector(
              `[data-taxonomy-parent-load="${itemSource}"]`
            );
            if (parentLoad) parentLoad.dataset.remaining = parentPage.remaining;
          }
        });
        renderResults();
      } catch (error) {
        if (error.name === "AbortError") return;
        const noResults = picker.querySelector("[data-tag-no-results]");
        if (noResults) {
          noResults.textContent = error.message;
          noResults.classList.remove("hidden");
        }
      } finally {
        if (serial === requestSerial) picker.classList.remove("is-loading");
      }
    };

    function toggleRecord(record) {
      if (selected.has(record.key)) selected.delete(record.key);
      else if (record.selectable) selected.set(record.key, { ...record, selected: true });
      fetchResults();
    }

    const hasExactMatch = () => {
      const query = (search?.value || "")
        .trim()
        .replace(/\s+/g, " ")
        .toLocaleLowerCase();
      if (!query) return false;
      return [...displayed.circuit_bench.values(), ...displayed.ecz.values()].some(
        (record) => record.label.toLocaleLowerCase() === query
          || record.identity?.toLocaleLowerCase() === query
          || record.aliases.some((alias) => alias.toLocaleLowerCase() === query)
      );
    };

    function updateCreateEligibility() {
      const createSection = picker.querySelector("[data-tag-create-section]");
      if (!createSection) return;
      const proposedLabel = (search?.value || "").trim().replace(/\s+/g, " ");
      const description = picker.querySelector("[data-tag-create-description]");
      const aliases = picker.querySelector("[data-tag-create-aliases]");
      const visibility = picker.querySelector("[data-tag-create-visibility]");
      const status = picker.querySelector("[data-tag-create-status]");
      const proposal = picker.querySelector("[data-tag-proposed-label]");
      const concept = picker.querySelector("[data-tag-concept]");
      const eligible = Boolean(proposedLabel) && !hasExactMatch();
      createParentEligible = eligible;
      createSection.classList.toggle("is-disabled", !eligible);
      createSection.setAttribute("aria-disabled", String(!eligible));
      description.disabled = !eligible;
      aliases.disabled = !eligible;
      visibility.disabled = !eligible;
      proposal.textContent = proposedLabel || "—";
      concept.textContent = {
        algorithm: "algorithm",
        code: "code",
        experiment: "circuit experiment",
      }[namespace()] || "scientific";
      const hasDescription = Boolean(description.value.trim());
      picker.querySelectorAll("[data-tag-create]").forEach((button) => {
        button.disabled = !eligible || !hasDescription;
      });
      const parentSelector = createSection.querySelector("[data-tag-parent-selector]");
      if (parentSelector) {
        parentSelector.classList.toggle("is-disabled", !eligible);
        parentSelector.setAttribute("aria-disabled", String(!eligible));
        parentSelector.inert = !eligible;
        const toggle = parentSelector.querySelector("[data-tag-parent-toggle]");
        const parentSearch = parentSelector.querySelector("[data-tag-parent-search]");
        if (toggle) toggle.disabled = !eligible;
        if (parentSearch) parentSearch.disabled = !eligible;
        if (!eligible) {
          const panel = parentSelector.querySelector("[data-tag-parent-panel]");
          if (panel) panel.hidden = true;
          if (toggle) {
            toggle.setAttribute("aria-expanded", "false");
            toggle.textContent = "Choose parent tags…";
          }
        }
      }
      if (!proposedLabel) status.textContent = "Type a proposed tag name above.";
      else if (!eligible) status.textContent = "That name exactly matches a tag or alias.";
      else if (!hasDescription) status.textContent = "Add a description to create this tag.";
      else if (status.dataset.error !== "true") {
        status.textContent = "This will create an immediately usable custom tag.";
      }
    }

    const createServerTag = async () => {
      const status = picker.querySelector("[data-tag-create-status]");
      const button = picker.querySelector("[data-tag-create]:not([hidden])");
      if (!picker.dataset.tagCreateUrl || button?.disabled) return;
      const payload = new URLSearchParams({
        namespace: namespace(),
        label: search.value.trim(),
        visibility: picker.querySelector("[data-tag-create-visibility]").value,
        description: picker.querySelector("[data-tag-create-description]").value.trim(),
        aliases: picker.querySelector("[data-tag-create-aliases]").value,
      });
      createParents.forEach((record) => {
        payload.append(
          record.source === "ecz" ? "ecz_parents" : "parents",
          record.database_id
        );
      });
      if (mode === "create") {
        selected.forEach((record) => {
          payload.append(
            record.source === "ecz" ? "ecz_parents" : "parents",
            record.database_id
          );
        });
      }
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
        const record = {
          key: `cb:${data.tag.id}`,
          source: "circuit_bench",
          label: data.tag.label,
          url: data.tag.url,
          selectable: true,
          selected: true,
          status: data.tag.status,
          colour: data.tag.display_color || "",
          namespace: data.tag.namespace,
          aliases: data.tag.aliases,
          database_id: data.tag.id,
          slug: data.tag.slug,
          source_suffix: "",
        };
        selected.set(record.key, record);
        createParents.clear();
        createParentDisplayed = { circuit_bench: new Map(), ecz: new Map() };
        search.value = "";
        picker.querySelector("[data-tag-create-description]").value = "";
        picker.querySelector("[data-tag-create-aliases]").value = "";
        picker.querySelector("[data-tag-create-visibility]").value = "public";
        status.textContent = `Created and selected “${record.label}”.`;
        await fetchResults();
      } catch (error) {
        status.dataset.error = "true";
        status.textContent = error.message;
        updateCreateEligibility();
      }
    };

    const restoreSnapshot = () => {
      selected = cloneSelectionMap(selectionSnapshot);
      createParents.clear();
      createParentDisplayed = { circuit_bench: new Map(), ecz: new Map() };
      if (matchInput) matchInput.value = matchSnapshot;
      search.value = "";
      fetchResults();
    };

    picker.querySelector("[data-tag-dialog-open]")?.addEventListener("click", () => {
      selectionSnapshot = cloneSelectionMap(selected);
      matchSnapshot = matchInput?.value || "all";
      createParents.clear();
      createParentDisplayed = { circuit_bench: new Map(), ecz: new Map() };
      search.value = "";
      fetchResults();
      dialog.showModal();
      search.focus();
    });
    picker.addEventListener("click", (event) => {
      const parentRemove = event.target.closest("[data-tag-create-parent-remove]");
      if (parentRemove) {
        createParents.delete(parentRemove.dataset.tagCreateParentRemove);
        fetchCreateParentResults();
        return;
      }
      const remove = event.target.closest("[data-tag-remove]");
      if (remove) {
        selected.delete(remove.dataset.tagRemove);
        fetchResults();
        if (!dialog?.open) {
          picker.dispatchEvent(new CustomEvent("control:commit", { bubbles: true }));
        }
        return;
      }
      if (event.target.closest("[data-tag-create]")) createServerTag();
    });
    const scheduleSearch = () => {
      const status = picker.querySelector("[data-tag-create-status]");
      if (status) status.dataset.error = "false";
      clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        displayed = { circuit_bench: new Map(), ecz: new Map() };
        parentDisplayed = { circuit_bench: new Map(), ecz: new Map() };
        nextOffsets = { circuit_bench: null, ecz: null };
        parentNextOffsets = { circuit_bench: null, ecz: null };
        fetchResults();
      }, 160);
      updateCreateEligibility();
    };
    search?.addEventListener("input", scheduleSearch);
    namespaceSelect?.addEventListener("change", scheduleSearch);
    picker.querySelector("[data-tag-create-description]")?.addEventListener(
      "input", updateCreateEligibility
    );
    picker.querySelector("[data-tag-create-aliases]")?.addEventListener(
      "input", updateCreateEligibility
    );
    const createParentSelector = picker.querySelector("[data-tag-parent-selector]");
    const createParentToggle = createParentSelector?.querySelector(
      "[data-tag-parent-toggle]"
    );
    const createParentPanel = createParentSelector?.querySelector(
      "[data-tag-parent-panel]"
    );
    const createParentSearch = createParentSelector?.querySelector(
      "[data-tag-parent-search]"
    );
    createParentToggle?.addEventListener("click", () => {
      if (!createParentEligible) return;
      const opening = createParentPanel.hidden;
      createParentPanel.hidden = !opening;
      createParentToggle.setAttribute("aria-expanded", String(opening));
      createParentToggle.textContent = opening
        ? "Hide parent choices"
        : "Choose parent tags…";
      if (opening) {
        fetchCreateParentResults();
        createParentSearch.focus();
      }
    });
    createParentSearch?.addEventListener("input", () => {
      clearTimeout(createParentSearchTimer);
      createParentSearchTimer = window.setTimeout(fetchCreateParentResults, 160);
    });
    picker.querySelectorAll("[data-tag-cancel]").forEach((button) => {
      button.addEventListener("click", () => {
        restoreSnapshot();
        dialog?.close();
      });
    });
    picker.querySelectorAll("[data-tag-apply]").forEach((button) => {
      button.addEventListener("click", () => {
        if (matchInput) matchInput.value = button.dataset.tagApply;
        renderSelected();
        dialog?.close();
        picker.dispatchEvent(new CustomEvent("control:commit", { bubbles: true }));
      });
    });
    dialog?.addEventListener("cancel", (event) => {
      event.preventDefault();
      restoreSnapshot();
      dialog.close();
    });
    renderSelected();
    if (mode === "create" || (mode === "filter" && selected.size)) fetchResults();
  };

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
    checkbox.dataset.tagId = record.id;
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
    const parentData = document.createElement("span");
    parentData.hidden = true;
    parentData.dataset.tagParents = "";
    record.parents.forEach((parent) => {
      const item = document.createElement("span");
      item.dataset.tagParent = "";
      item.dataset.parentId = parent.id;
      item.dataset.parentLabel = parent.label;
      item.dataset.parentStatus = parent.status;
      item.dataset.parentColor = parent.display_color || "";
      item.dataset.parentUrl = parent.url;
      item.dataset.parentNamespace = parent.namespace;
      parentData.append(item);
    });
    choice.append(main, info, aliasData, parentData);
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
      visibility: picker.querySelector("[data-tag-create-visibility]").value,
      description: picker.querySelector("[data-tag-create-description]").value.trim(),
      aliases: picker.querySelector("[data-tag-create-aliases]").value,
    });
    picker.querySelectorAll(
      "[data-tag-create-section] [data-tag-parent-choice]:checked"
    ).forEach((checkbox) => payload.append("parents", checkbox.value));
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
      picker.querySelector("[data-tag-create-visibility]").value = "public";
      picker.querySelectorAll(
        "[data-tag-create-section] [data-tag-parent-choice]:checked"
      ).forEach((checkbox) => { checkbox.checked = false; });
      const parentSelector = picker.querySelector(
        "[data-tag-create-section] [data-tag-parent-selector]"
      );
      if (parentSelector) updateParentSelector(parentSelector);
      updateTagPicker(picker);
      status.textContent = `Created and selected “${data.tag.label}”.`;
    } catch (error) {
      status.dataset.error = "true";
      status.textContent = error.message;
      updateTagPicker(picker);
    }
  };

  document.querySelectorAll("[data-tag-picker]").forEach((picker) => {
    if (picker.dataset.tagSearchUrl) {
      initServerTagPicker(picker);
      return;
    }
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
      const parentSelector = picker.querySelector(
        "[data-tag-create-section] [data-tag-parent-selector]"
      );
      parentSelector?.querySelectorAll("[data-tag-parent-choice]:checked")
        .forEach((checkbox) => { checkbox.checked = false; });
      if (parentSelector) updateParentSelector(parentSelector);
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
          picker.dispatchEvent(new CustomEvent("control:commit", {
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
    picker.querySelector("[data-tag-create-visibility]")?.addEventListener(
      "change", updateAfterCreateInput
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
        picker.dispatchEvent(new CustomEvent("control:commit", {
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

  const makeSelectedParent = (checkbox) => {
    const tag = makeSelectedTag(checkbox);
    tag.dataset.selectedParent = checkbox.value;
    tag.removeAttribute("data-selected-tag");
    const remove = tag.querySelector("[data-tag-remove]");
    remove.dataset.tagParentRemove = checkbox.value;
    delete remove.dataset.tagRemove;
    remove.setAttribute("aria-label", `Remove ${checkbox.dataset.label} as a parent`);
    return tag;
  };

  const updateParentSelector = (selector) => {
    const query = (selector.querySelector("[data-tag-parent-search]")?.value || "")
      .trim().toLocaleLowerCase();
    const choices = [...selector.querySelectorAll("[data-tag-parent-choice-card]")];
    const selected = choices
      .map((choice) => choice.querySelector("[data-tag-parent-choice]"))
      .filter((checkbox) => checkbox.checked);
    const selectedIds = new Set(selected.map((checkbox) => checkbox.value));
    const summary = selector.querySelector("[data-tag-parent-summary]");
    summary.replaceChildren(...selected.map(makeSelectedParent));
    if (!selected.length) {
      const empty = document.createElement("span");
      empty.className = "tag-picker-empty-summary";
      empty.textContent = "No parent tags selected";
      summary.append(empty);
    }

    let visibleCount = 0;
    choices.forEach((choice) => {
      const checkbox = choice.querySelector("[data-tag-parent-choice]");
      const aliases = aliasEntries(choice);
      const aliasMatch = query
        ? aliases.find((alias) => alias.normalized.includes(query))
        : null;
      const matches = !query
        || choice.dataset.tagLabel.includes(query)
        || Boolean(aliasMatch);
      choice.hidden = !checkbox.checked && !matches;
      choice.classList.toggle("is-selected", checkbox.checked);
      const glyph = choice.querySelector(".tag-glyph");
      glyph.textContent = checkbox.checked
        ? "✓"
        : choice.dataset.tagStatus === "official" ? "◆" : "◇";
      const aliasLabel = choice.querySelector("[data-tag-alias-match]");
      aliasLabel.textContent = aliasMatch ? `(${aliasMatch.display})` : "";
      if (!choice.hidden) visibleCount += 1;
    });
    const noResults = selector.querySelector("[data-tag-parent-no-results]");
    noResults.classList.toggle("hidden", visibleCount > 0);
    renderContextParents(
      selector.querySelector("[data-tag-context-parents]"),
      choices,
      selectedIds,
      Boolean(query)
    );
  };

  document.querySelectorAll("[data-tag-parent-selector]").forEach((selector) => {
    if (selector.matches("[data-dynamic-tag-parent-selector]")) return;
    const toggle = selector.querySelector("[data-tag-parent-toggle]");
    const panel = selector.querySelector("[data-tag-parent-panel]");
    const search = selector.querySelector("[data-tag-parent-search]");
    toggle.addEventListener("click", () => {
      const opening = panel.hidden;
      panel.hidden = !opening;
      toggle.setAttribute("aria-expanded", String(opening));
      toggle.textContent = opening ? "Hide parent choices" : "Choose parent tags…";
      if (opening) search.focus();
    });
    selector.addEventListener("change", (event) => {
      if (event.target.matches("[data-tag-parent-choice]")) {
        updateParentSelector(selector);
      }
    });
    selector.addEventListener("click", (event) => {
      const remove = event.target.closest("[data-tag-parent-remove]");
      if (!remove) return;
      const checkbox = [...selector.querySelectorAll("[data-tag-parent-choice]")]
        .find((candidate) => candidate.value === remove.dataset.tagParentRemove);
      if (checkbox) checkbox.checked = false;
      updateParentSelector(selector);
    });
    search.addEventListener("input", () => updateParentSelector(selector));
    updateParentSelector(selector);
  });
})();
