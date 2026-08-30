(() => {
  "use strict";

  const grids = [...document.querySelectorAll("[data-filter-grid]")];
  if (!grids.length) return;

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let activeOverlay = null;
  let resizeFrame = null;

  const directCells = (gridCells) => [...gridCells.children]
    .filter((element) => element.matches("[data-filter-grid-cell]"));

  const columnCount = (gridCells) => {
    const columns = getComputedStyle(gridCells).gridTemplateColumns
      .split(" ")
      .filter(Boolean);
    return Math.max(columns.length, 1);
  };

  const layoutFor = (gridCells) => {
    const cells = directCells(gridCells);
    const gridRect = gridCells.getBoundingClientRect();
    const columns = columnCount(gridCells);
    const columnWidth = gridRect.width / columns;
    const rowTops = [...new Set(cells.map((cell) => Math.round(
      cell.getBoundingClientRect().top - gridRect.top
    )))].sort((left, right) => left - right);
    const entries = new Map();
    const blocked = new Set();

    cells.forEach((cell) => {
      const rect = cell.getBoundingClientRect();
      const relativeTop = Math.round(rect.top - gridRect.top);
      const row = rowTops.findIndex((top) => Math.abs(top - relativeTop) <= 2);
      const column = Math.max(0, Math.min(
        columns - 1,
        Math.round((rect.left - gridRect.left) / columnWidth)
      ));
      const span = Math.max(1, Math.round(rect.width / columnWidth));
      const slot = row * columns + column;
      entries.set(cell, { row, column, span, slot });
      if (cell.matches("[data-filter-tag-cell]")) {
        for (let index = 0; index < span; index += 1) blocked.add(slot + index);
      }
    });

    return {
      blocked,
      columns,
      entries,
      rowCount: Math.max(rowTops.length, 1),
    };
  };

  const slotPosition = (slot, columns) => ({
    column: (slot % columns) + 1,
    row: Math.floor(slot / columns) + 1,
  });

  const blockIsClear = (start, length, blocked) => {
    if (start < 0) return false;
    for (let offset = 0; offset < length; offset += 1) {
      if (blocked.has(start + offset)) return false;
    }
    return true;
  };

  const choicePlacement = (layout, sourceSlot, optionCount) => {
    const blockLength = optionCount + 1;
    const capacity = layout.rowCount * layout.columns;
    const candidates = [];
    const searchCapacity = capacity + Math.ceil(blockLength / layout.columns)
      * layout.columns;
    for (let start = 0; start <= searchCapacity - blockLength; start += 1) {
      if (!blockIsClear(start, blockLength, layout.blocked)) continue;
      const end = start + blockLength - 1;
      const anchorSlot = Math.max(start, Math.min(sourceSlot, end));
      const rowsUsed = Math.ceil((end + 1) / layout.columns);
      candidates.push({
        anchorSlot,
        anchorDistance: Math.abs(anchorSlot - sourceSlot),
        blockDistance: Math.abs(((start + end) / 2) - sourceSlot),
        optionSlots: Array.from(
          { length: blockLength },
          (_value, index) => start + index
        ).filter((slot) => slot !== anchorSlot),
        rowsAdded: Math.max(0, rowsUsed - layout.rowCount),
        splitPenalty: anchorSlot === start || anchorSlot === end ? 0 : 1,
      });
    }
    candidates.sort((left, right) => (
      left.rowsAdded - right.rowsAdded
      || left.anchorDistance - right.anchorDistance
      || left.splitPenalty - right.splitPenalty
      || left.blockDistance - right.blockDistance
    ));
    return candidates[0];
  };

  const positionOverlayCell = (cell, slot, columns) => {
    const position = slotPosition(slot, columns);
    cell.style.gridColumn = String(position.column);
    cell.style.gridRow = String(position.row);
  };

  const lockBaseLayout = (layout) => {
    const lockedCells = [];
    layout.entries.forEach((entry, cell) => {
      cell.style.gridColumn = `${entry.column + 1} / span ${entry.span}`;
      cell.style.gridRow = String(entry.row + 1);
      lockedCells.push(cell);
    });
    return lockedCells;
  };

  const unlockBaseLayout = (cells = []) => {
    cells.forEach((cell) => {
      cell.style.removeProperty("grid-column");
      cell.style.removeProperty("grid-row");
    });
  };

  const updateChoiceCell = (source) => {
    const select = source.querySelector("[data-filter-choice-input]");
    const selected = select.options[select.selectedIndex];
    source.querySelector("[data-filter-cell-value]").textContent = selected.textContent;
    source.classList.toggle("is-filtered", Boolean(select.value));
  };

  const finishOverlayRemoval = (overlay) => {
    const shouldRestoreFocus = activeOverlay === overlay && overlay.restoreFocus;
    overlay.elements.forEach((element) => element.remove());
    unlockBaseLayout(overlay.lockedCells);
    overlay.trigger?.setAttribute("aria-expanded", "false");
    if (activeOverlay === overlay) activeOverlay = null;
    if (shouldRestoreFocus) {
      requestAnimationFrame(() => {
        if (
          document.activeElement === document.body
          && overlay.trigger?.isConnected
        ) {
          overlay.trigger.focus({ preventScroll: true });
        }
      });
    }
  };

  const closeOverlay = ({ immediate = false, restoreFocus = false } = {}) => {
    const overlay = activeOverlay;
    if (!overlay) return;
    overlay.dragging = null;
    overlay.restoreFocus = overlay.restoreFocus || restoreFocus;
    if (overlay.restoreFocus && overlay.trigger?.isConnected) {
      overlay.trigger.focus({ preventScroll: true });
    }
    if (immediate || reducedMotion.matches) {
      finishOverlayRemoval(overlay);
      return;
    }
    const ordered = [...overlay.elements].sort((left, right) => (
      Number(right.dataset.filterDistance || 0)
      - Number(left.dataset.filterDistance || 0)
    ));
    ordered.forEach((element, index) => {
      element.style.transitionDelay = `${index * 28}ms`;
      element.classList.remove("is-visible");
    });
    window.setTimeout(
      () => finishOverlayRemoval(overlay),
      150 + ordered.length * 28
    );
  };

  const openChoice = (grid, source) => {
    closeOverlay({ immediate: true });
    const gridCells = grid.querySelector("[data-filter-grid-cells]");
    const layout = layoutFor(gridCells);
    const sourceLayout = layout.entries.get(source);
    const select = source.querySelector("[data-filter-choice-input]");
    const options = [...select.options];
    if (!sourceLayout || !options.length) {
      select.focus();
      return;
    }
    const placement = choicePlacement(layout, sourceLayout.slot, options.length);
    if (!placement) {
      select.focus();
      return;
    }

    const trigger = source.querySelector("[data-filter-choice-trigger]");
    trigger.setAttribute("aria-expanded", "true");
    const label = source.querySelector(".filter-grid-cell-title").textContent;
    const anchor = document.createElement("button");
    anchor.type = "button";
    anchor.className = "filter-choice-overlay-cell filter-choice-overlay-anchor";
    anchor.dataset.filterOverlayCancel = "true";
    anchor.dataset.filterDistance = "0";
    const anchorLabel = document.createElement("span");
    anchorLabel.textContent = label;
    const anchorInstruction = document.createElement("span");
    anchorInstruction.textContent = "Choose filter";
    anchor.append(anchorLabel, anchorInstruction);
    positionOverlayCell(anchor, placement.anchorSlot, layout.columns);

    const optionCells = options.map((option, index) => {
      const button = document.createElement("button");
      const slot = placement.optionSlots[index];
      const distance = Math.abs(slot - placement.anchorSlot);
      button.type = "button";
      button.className = "filter-choice-overlay-cell filter-choice-overlay-option";
      button.dataset.filterOverlayOption = option.value;
      button.dataset.filterDistance = String(distance);
      button.setAttribute("aria-pressed", option.selected ? "true" : "false");
      button.textContent = `${option.selected ? "✓ " : ""}${option.textContent}`;
      button.style.setProperty(
        "--filter-telescope-origin",
        slot < placement.anchorSlot ? "right" : "left"
      );
      button.style.transitionDelay = `${Math.max(0, distance - 1) * 42}ms`;
      positionOverlayCell(button, slot, layout.columns);
      return button;
    });

    const elements = [anchor, ...optionCells];
    const lockedCells = lockBaseLayout(layout);
    gridCells.append(...elements);
    activeOverlay = {
      elements,
      grid,
      gridCells,
      lockedCells,
      select,
      source,
      trigger,
      type: "choice",
    };
    requestAnimationFrame(() => {
      elements.forEach((element) => element.classList.add("is-visible"));
      const selected = optionCells.find(
        (element) => element.getAttribute("aria-pressed") === "true"
      );
      (selected || optionCells[0])?.focus({ preventScroll: true });
    });
  };

  const makeRangeField = (labelText, value, placeholder, key) => {
    const label = document.createElement("label");
    label.className = "filter-range-field";
    const title = document.createElement("span");
    title.textContent = labelText;
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.step = "1";
    input.value = value;
    input.placeholder = placeholder;
    input.dataset[key] = "true";
    label.append(title, input);
    return label;
  };

  const makeRangeHandle = (kind) => {
    const handle = document.createElement("button");
    handle.type = "button";
    handle.className = `filter-range-handle filter-range-handle-${kind}`;
    handle.dataset.filterRangeHandle = kind;
    const label = document.createElement("span");
    label.className = "filter-range-handle-label";
    handle.appendChild(label);
    return handle;
  };

  const rangeValues = (overlay) => {
    const minimum = Math.max(0, Number(overlay.minimumEditor.value || 0));
    const maximum = overlay.maximumEditor.value === ""
      ? null
      : Math.max(0, Number(overlay.maximumEditor.value));
    return { maximum, minimum };
  };

  const setHandle = (handle, percent, label, edge) => {
    handle.style.left = `${percent}%`;
    handle.classList.toggle("is-left-edge", edge === "left");
    handle.classList.toggle("is-right-edge", edge === "right");
    handle.querySelector(".filter-range-handle-label").textContent = label;
    handle.setAttribute("aria-label", `${label}; drag or use arrow keys to change`);
  };

  const updateRangeOverlay = (overlay) => {
    let { maximum, minimum } = rangeValues(overlay);
    if (maximum !== null && minimum > maximum) {
      if (document.activeElement === overlay.minimumEditor || overlay.dragging === "min") {
        minimum = maximum;
        overlay.minimumEditor.value = String(minimum);
      } else {
        maximum = minimum;
        overlay.maximumEditor.value = String(maximum);
      }
    }
    const domainSpan = Math.max(overlay.domainMaximum - overlay.domainMinimum, 1);
    const minimumPercent = Math.max(0, Math.min(
      100,
      ((minimum - overlay.domainMinimum) / domainSpan) * 100
    ));
    const maximumPercent = maximum === null
      ? 100
      : Math.max(0, Math.min(
        100,
        ((maximum - overlay.domainMinimum) / domainSpan) * 100
      ));

    overlay.minimumInput.value = minimum > 0 ? String(minimum) : "";
    overlay.maximumInput.value = maximum === null ? "" : String(maximum);
    overlay.source.querySelector("[data-filter-cell-value]").textContent = (
      `${minimum}–${maximum === null ? "∞" : maximum}`
    );
    overlay.source.classList.toggle("is-filtered", minimum > 0 || maximum !== null);
    overlay.leftShade.style.width = `${minimumPercent}%`;
    overlay.rightShade.style.left = `${maximumPercent}%`;
    overlay.rightShade.hidden = maximum === null;
    setHandle(
      overlay.minimumHandle,
      minimumPercent,
      `min ${minimum}`,
      minimumPercent < 8 ? "left" : ""
    );
    setHandle(
      overlay.maximumHandle,
      maximumPercent,
      `max ${maximum === null ? "∞" : maximum}`,
      maximumPercent > 92 ? "right" : ""
    );
  };

  const openRange = (grid, source) => {
    closeOverlay({ immediate: true });
    const gridCells = grid.querySelector("[data-filter-grid-cells]");
    const layout = layoutFor(gridCells);
    const sourceLayout = layout.entries.get(source);
    if (!sourceLayout) return;

    const minimumInput = source.querySelector("[data-filter-range-min]");
    const maximumInput = source.querySelector("[data-filter-range-max]");
    const trigger = source.querySelector("[data-filter-range-trigger]");
    trigger.setAttribute("aria-expanded", "true");

    const editor = document.createElement("section");
    editor.className = "filter-range-overlay";
    editor.dataset.filterDistance = "0";
    editor.style.gridColumn = "1 / -1";
    editor.style.gridRow = String(sourceLayout.row + 1);
    editor.style.setProperty("--filter-editor-columns", String(layout.columns));

    const minimumEditor = makeRangeField(
      "Minimum",
      minimumInput.value || "0",
      "0",
      "filterRangeMinimumEditor"
    );
    const maximumEditor = makeRangeField(
      "Maximum",
      maximumInput.value,
      "∞",
      "filterRangeMaximumEditor"
    );
    const histogram = document.createElement("section");
    histogram.className = "filter-range-histogram-cell";
    const histogramHead = document.createElement("header");
    const histogramLabel = document.createElement("strong");
    histogramLabel.textContent = source.dataset.histogramLabel;
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "filter-range-reset";
    reset.dataset.filterRangeReset = "true";
    reset.textContent = "Reset limits";
    histogramHead.append(histogramLabel, reset);

    const plot = document.createElement("div");
    plot.className = "filter-range-plot";
    plot.setAttribute("role", "img");
    plot.setAttribute(
      "aria-label",
      `${source.dataset.histogramLabel}; draggable minimum and maximum limits`
    );
    const bars = document.createElement("div");
    bars.className = "filter-range-bars";
    const counts = source.dataset.histogramCounts.split(",").map(Number);
    const largestCount = Math.max(...counts, 1);
    counts.forEach((count) => {
      const bar = document.createElement("span");
      bar.style.height = `${Math.round((count / largestCount) * 100)}%`;
      bars.appendChild(bar);
    });
    const leftShade = document.createElement("span");
    leftShade.className = "filter-range-shade filter-range-shade-left";
    const rightShade = document.createElement("span");
    rightShade.className = "filter-range-shade filter-range-shade-right";
    const minimumHandle = makeRangeHandle("min");
    const maximumHandle = makeRangeHandle("max");
    plot.append(bars, leftShade, rightShade, minimumHandle, maximumHandle);
    histogram.append(histogramHead, plot);
    editor.append(minimumEditor, maximumEditor, histogram);
    const lockedCells = lockBaseLayout(layout);
    gridCells.appendChild(editor);

    activeOverlay = {
      domainMaximum: Number(source.dataset.domainMax),
      domainMinimum: Number(source.dataset.domainMin),
      dragging: null,
      editor,
      elements: [editor],
      grid,
      gridCells,
      histogram,
      leftShade,
      lockedCells,
      maximumEditor: maximumEditor.querySelector("input"),
      maximumHandle,
      maximumInput,
      minimumEditor: minimumEditor.querySelector("input"),
      minimumHandle,
      minimumInput,
      plot,
      rightShade,
      source,
      trigger,
      type: "range",
    };
    updateRangeOverlay(activeOverlay);
    requestAnimationFrame(() => {
      editor.classList.add("is-visible");
      activeOverlay?.minimumEditor.focus({ preventScroll: true });
    });
  };

  const updateDraggedRange = (clientX) => {
    const overlay = activeOverlay;
    if (!overlay || overlay.type !== "range" || !overlay.dragging) return;
    const bounds = overlay.plot.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - bounds.left) / bounds.width));
    const value = Math.round(
      overlay.domainMinimum
      + ratio * (overlay.domainMaximum - overlay.domainMinimum)
    );
    const values = rangeValues(overlay);
    if (overlay.dragging === "min") {
      const ceiling = values.maximum ?? overlay.domainMaximum;
      overlay.minimumEditor.value = String(Math.min(value, ceiling));
    } else {
      overlay.maximumEditor.value = String(Math.max(value, values.minimum));
    }
    updateRangeOverlay(overlay);
  };

  const syncTagPanel = (panel) => {
    const picker = panel.querySelector("[data-tag-picker]");
    if (!picker) return;
    const selected = picker.querySelectorAll('[data-tag-choice] input:checked').length;
    const match = picker.querySelector("[data-tag-match-input]")?.value || "all";
    panel.classList.toggle("is-filtered", selected > 0);
    panel.querySelector("[data-tag-rule-label]").textContent = (
      match === "any" ? "any of" : "all of"
    );
  };

  const resizeTagPanel = (panel) => {
    const gridCells = panel.closest("[data-filter-grid-cells]");
    const columns = columnCount(gridCells);
    const trackWidth = gridCells.getBoundingClientRect().width / columns;
    const summaryItems = [
      ...panel.querySelectorAll("[data-tag-summary] > *"),
      panel.querySelector("[data-tag-dialog-open]"),
    ].filter(Boolean);
    const itemWidth = summaryItems.reduce(
      (total, item) => total + item.getBoundingClientRect().width,
      Math.max(0, summaryItems.length - 1) * 5
    );
    const headingWidth = panel.querySelector(".filter-grid-tag-heading").scrollWidth;
    const panelStyle = getComputedStyle(panel);
    const padding = parseFloat(panelStyle.paddingLeft) + parseFloat(panelStyle.paddingRight);
    const desiredWidth = Math.max(itemWidth + padding, headingWidth + padding);
    const span = Math.max(2, Math.min(columns, Math.ceil(desiredWidth / trackWidth)));
    if (panel.style.getPropertyValue("--filter-tag-span") !== String(span)) {
      panel.style.setProperty("--filter-tag-span", String(span));
    }
  };

  const resizeAllTagPanels = () => {
    grids.forEach((grid) => {
      grid.querySelectorAll("[data-filter-tag-cell]").forEach((panel) => {
        syncTagPanel(panel);
        resizeTagPanel(panel);
      });
    });
  };

  const scheduleTagResize = () => {
    if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      resizeFrame = null;
      resizeAllTagPanels();
    });
  };

  grids.forEach((grid) => {
    grid.dataset.enhanced = "true";
    grid.addEventListener("click", (event) => {
      const option = event.target.closest("[data-filter-overlay-option]");
      if (option && activeOverlay?.type === "choice") {
        activeOverlay.select.value = option.dataset.filterOverlayOption;
        activeOverlay.select.dispatchEvent(new Event("change", { bubbles: true }));
        updateChoiceCell(activeOverlay.source);
        closeOverlay({ restoreFocus: true });
        return;
      }
      if (event.target.closest("[data-filter-overlay-cancel]")) {
        closeOverlay({ restoreFocus: true });
        return;
      }
      const reset = event.target.closest("[data-filter-range-reset]");
      if (reset && activeOverlay?.type === "range") {
        activeOverlay.minimumEditor.value = "0";
        activeOverlay.maximumEditor.value = "";
        updateRangeOverlay(activeOverlay);
        closeOverlay({ immediate: true, restoreFocus: true });
        return;
      }
      const choiceTrigger = event.target.closest("[data-filter-choice-trigger]");
      if (choiceTrigger) {
        openChoice(grid, choiceTrigger.closest("[data-filter-choice-cell]"));
        return;
      }
      const rangeTrigger = event.target.closest("[data-filter-range-trigger]");
      if (rangeTrigger) {
        openRange(grid, rangeTrigger.closest("[data-filter-range-cell]"));
      }
    });

    grid.addEventListener("input", (event) => {
      if (
        activeOverlay?.type === "range"
        && event.target.matches(
          "[data-filter-range-minimum-editor], [data-filter-range-maximum-editor]"
        )
      ) {
        updateRangeOverlay(activeOverlay);
      }
    });

    grid.addEventListener("pointerdown", (event) => {
      const handle = event.target.closest("[data-filter-range-handle]");
      if (!handle || activeOverlay?.type !== "range") return;
      event.preventDefault();
      activeOverlay.dragging = handle.dataset.filterRangeHandle;
    });

    grid.addEventListener("filtergrid:tags-changed", scheduleTagResize);
  });

  document.addEventListener("pointerdown", (event) => {
    if (!activeOverlay) return;
    const inside = activeOverlay.elements.some((element) => element.contains(event.target));
    if (!inside) closeOverlay();
  });

  document.addEventListener("pointermove", (event) => {
    if (activeOverlay?.type !== "range" || !activeOverlay.dragging) return;
    event.preventDefault();
    updateDraggedRange(event.clientX);
  });

  document.addEventListener("pointerup", () => {
    if (activeOverlay?.type === "range") activeOverlay.dragging = null;
  });

  document.addEventListener("keydown", (event) => {
    if (!activeOverlay) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeOverlay({ restoreFocus: true });
      return;
    }
    if (activeOverlay.type === "range" && event.key === "Enter") {
      event.preventDefault();
      closeOverlay({ restoreFocus: true });
      return;
    }
    const handle = event.target.closest("[data-filter-range-handle]");
    if (
      activeOverlay.type !== "range"
      || !handle
      || !["ArrowLeft", "ArrowRight"].includes(event.key)
    ) return;
    event.preventDefault();
    const direction = event.key === "ArrowLeft" ? -1 : 1;
    const step = event.shiftKey ? 5 : 1;
    const values = rangeValues(activeOverlay);
    if (handle.dataset.filterRangeHandle === "min") {
      const ceiling = values.maximum ?? activeOverlay.domainMaximum;
      activeOverlay.minimumEditor.value = String(Math.max(
        0,
        Math.min(ceiling, values.minimum + direction * step)
      ));
    } else {
      const current = values.maximum ?? activeOverlay.domainMaximum;
      activeOverlay.maximumEditor.value = String(Math.max(
        values.minimum,
        Math.min(activeOverlay.domainMaximum, current + direction * step)
      ));
    }
    const kind = handle.dataset.filterRangeHandle;
    updateRangeOverlay(activeOverlay);
    requestAnimationFrame(() => activeOverlay?.editor
      .querySelector(`[data-filter-range-handle="${kind}"]`)
      ?.focus({ preventScroll: true }));
  });

  const observer = new ResizeObserver(scheduleTagResize);
  grids.forEach((grid) => observer.observe(grid));
  resizeAllTagPanels();
})();
