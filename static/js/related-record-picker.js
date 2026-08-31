(() => {
  "use strict";

  const pickers = [...document.querySelectorAll("[data-related-record-picker]")];
  if (!pickers.length) return;

  const recordFromDataset = (element) => ({
    identifier: element.dataset.recordIdentifier,
    label: element.dataset.recordLabel,
    secondary_label: element.dataset.recordSecondaryLabel,
    description: element.dataset.recordDescription,
    curation_status: element.dataset.recordCurationStatus,
    curation_label: element.dataset.recordCurationLabel,
    detail_url: element.dataset.recordDetailUrl,
  });

  const cloneRecords = (records) => records.map((record) => ({ ...record }));

  pickers.forEach((picker) => {
    const dialog = picker.querySelector("[data-related-record-dialog]");
    const opener = picker.querySelector("[data-related-record-open]");
    const search = picker.querySelector("[data-related-record-search]");
    const selectedArea = picker.querySelector("[data-related-record-selected]");
    const resultsArea = picker.querySelector("[data-related-record-results]");
    const status = picker.querySelector("[data-related-record-status]");
    const pagination = picker.querySelector("[data-related-record-pagination]");
    const pageStatus = picker.querySelector("[data-related-record-page-status]");
    const inputArea = picker.querySelector("[data-related-record-inputs]");
    const summary = picker.querySelector("[data-related-record-summary]");
    const gridCell = picker.closest("[data-filter-related-record-cell]");
    const initial = [...picker.querySelectorAll("[data-record-identifier]")]
      .map(recordFromDataset);
    let committed = cloneRecords(initial);
    let working = cloneRecords(initial);
    let currentResults = [];
    let page = 1;
    let pages = 1;
    let searchTimer = null;
    let requestController = null;

    const selectedIndex = (identifier) => working.findIndex(
      (record) => record.identifier === identifier
    );

    const makeStatus = (record) => {
      const badge = document.createElement("span");
      badge.className = `related-record-curation related-record-curation-${record.curation_status}`;
      badge.textContent = record.curation_label;
      return badge;
    };

    const renderSelected = () => {
      selectedArea.replaceChildren();
      if (!working.length) {
        const empty = document.createElement("span");
        empty.className = "muted";
        empty.textContent = `No ${picker.dataset.pluralLabel} selected; all are permitted.`;
        selectedArea.append(empty);
        return;
      }
      working.forEach((record) => {
        const card = document.createElement("span");
        card.className = "related-record-selected-card";
        const label = document.createElement("span");
        label.textContent = record.label;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.dataset.relatedRecordRemove = record.identifier;
        remove.setAttribute("aria-label", `Remove ${record.label}`);
        remove.textContent = "×";
        card.append(makeStatus(record), label, remove);
        selectedArea.append(card);
      });
    };

    const makeResult = (record) => {
      const selected = selectedIndex(record.identifier) >= 0;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "related-record-result";
      button.dataset.relatedRecordResult = record.identifier;
      button.setAttribute("aria-pressed", String(selected));

      const heading = document.createElement("span");
      heading.className = "related-record-result-heading";
      const name = document.createElement("strong");
      name.textContent = record.label;
      const slug = document.createElement("code");
      slug.textContent = record.secondary_label;
      heading.append(name, slug, makeStatus(record));

      const description = document.createElement("span");
      description.className = "related-record-result-description";
      description.textContent = record.description;
      const action = document.createElement("span");
      action.className = "related-record-result-action";
      action.textContent = selected ? "Remove" : "Select";
      button.append(heading, description, action);
      return button;
    };

    const renderResults = () => {
      resultsArea.replaceChildren();
      if (!currentResults.length) {
        const empty = document.createElement("p");
        empty.className = "tag-no-results";
        empty.textContent = "No matching records.";
        resultsArea.append(empty);
      } else {
        const grouped = new Map();
        currentResults.forEach((record) => {
          const key = record.curation_status;
          if (!grouped.has(key)) grouped.set(key, []);
          grouped.get(key).push(record);
        });
        ["official", "community", "deprecated"].forEach((groupKey) => {
          const records = grouped.get(groupKey);
          if (!records?.length) return;
          const section = document.createElement("section");
          section.className = "related-record-result-group";
          const heading = document.createElement("h4");
          heading.textContent = records[0].curation_label;
          const list = document.createElement("div");
          records.forEach((record) => list.append(makeResult(record)));
          section.append(heading, list);
          resultsArea.append(section);
        });
      }
      pagination.hidden = pages <= 1;
      pagination.querySelector('[data-related-record-page="previous"]').disabled = page <= 1;
      pagination.querySelector('[data-related-record-page="next"]').disabled = page >= pages;
      pageStatus.textContent = `Page ${page} of ${pages}`;
    };

    const renderSummary = () => {
      inputArea.replaceChildren();
      committed.forEach((record) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = picker.dataset.inputName;
        input.value = record.identifier;
        inputArea.append(input);
      });
      let text = "Any";
      if (committed.length) {
        text = committed[0].label;
        if (committed.length > 1) text += ` +${committed.length - 1}`;
      }
      summary.textContent = text;
      const fullSelection = committed.length
        ? committed.map((record) => record.label).join(", ")
        : "Any";
      opener.title = fullSelection;
      opener.setAttribute("aria-label", `${picker.dataset.pluralLabel}: ${fullSelection}`);
      gridCell.classList.toggle("is-filtered", committed.length > 0);
    };

    const loadResults = async () => {
      requestController?.abort();
      requestController = new AbortController();
      const url = new URL(picker.dataset.searchUrl, window.location.origin);
      url.searchParams.set("q", search.value.trim());
      url.searchParams.set("page", String(page));
      status.textContent = `Searching ${picker.dataset.pluralLabel}…`;
      try {
        const response = await fetch(url, {
          headers: { Accept: "application/json" },
          signal: requestController.signal,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        currentResults = payload.results;
        page = payload.pagination.page;
        pages = payload.pagination.pages;
        status.textContent = `${currentResults.length} ${currentResults.length === 1 ? picker.dataset.singularLabel : picker.dataset.pluralLabel} on this page; official records are listed first.`;
        renderResults();
      } catch (error) {
        if (error.name === "AbortError") return;
        currentResults = [];
        pages = 1;
        status.textContent = `Could not load ${picker.dataset.pluralLabel}. Try again.`;
        renderResults();
      }
    };

    const cancel = () => {
      working = cloneRecords(committed);
      requestController?.abort();
      dialog.close();
      opener.setAttribute("aria-expanded", "false");
    };

    opener.addEventListener("click", () => {
      working = cloneRecords(committed);
      currentResults = [];
      page = 1;
      pages = 1;
      search.value = "";
      renderSelected();
      renderResults();
      dialog.showModal();
      opener.setAttribute("aria-expanded", "true");
      search.focus();
      loadResults();
    });

    search.addEventListener("input", () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        page = 1;
        loadResults();
      }, 180);
    });

    selectedArea.addEventListener("click", (event) => {
      const remove = event.target.closest("[data-related-record-remove]");
      if (!remove) return;
      working = working.filter(
        (record) => record.identifier !== remove.dataset.relatedRecordRemove
      );
      renderSelected();
      renderResults();
    });

    resultsArea.addEventListener("click", (event) => {
      const result = event.target.closest("[data-related-record-result]");
      if (!result) return;
      const record = currentResults.find(
        (candidate) => candidate.identifier === result.dataset.relatedRecordResult
      );
      if (!record) return;
      const index = selectedIndex(record.identifier);
      if (index >= 0) {
        working.splice(index, 1);
      } else {
        working.push({ ...record });
      }
      renderSelected();
      renderResults();
    });

    pagination.addEventListener("click", (event) => {
      const control = event.target.closest("[data-related-record-page]");
      if (!control) return;
      page += control.dataset.relatedRecordPage === "next" ? 1 : -1;
      loadResults();
    });

    picker.querySelectorAll("[data-related-record-cancel]").forEach((button) => {
      button.addEventListener("click", cancel);
    });
    picker.querySelector("[data-related-record-apply]").addEventListener("click", () => {
      committed = cloneRecords(working);
      renderSummary();
      dialog.close();
      opener.setAttribute("aria-expanded", "false");
      picker.dispatchEvent(new CustomEvent("filterquery:change", {
        bubbles: true,
      }));
    });
    picker.addEventListener("filtergrid:clear", () => {
      committed = [];
      working = [];
      renderSummary();
      renderSelected();
      renderResults();
      picker.dispatchEvent(new CustomEvent("filterquery:change", {
        bubbles: true,
      }));
    });
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      cancel();
    });

    renderSummary();
  });
})();
