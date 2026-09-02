(() => {
  "use strict";

  // Composite controls emit `control:commit`; related pickers accept
  // `control:clear`; tag pickers emit `tagpicker:layoutchange` after reflow.

  const grids = [...document.querySelectorAll("[data-control-grid]")];
  if (!grids.length) return;

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let activeOverlay = null;
  let resizeFrame = null;

  const notifyControlCommit = (element) => {
    element.closest("form")?.dispatchEvent(new CustomEvent("control:commit"));
  };

  const setControlState = (cell, active) => {
    const stateClass = cell?.dataset.controlStateClass;
    if (stateClass) cell.classList.toggle(stateClass, active);
  };

  const updateAppliedCount = (grid) => {
    const output = grid?.querySelector("[data-filter-applied-count]");
    if (!output) return;
    const count = grid.querySelectorAll(
      "[data-control-grid-cell].is-applied"
    ).length;
    output.textContent = `, ${count} applied`;
  };

  const directCells = (gridCells) => [...gridCells.children]
    .filter((element) => element.matches("[data-control-grid-cell]"));

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
    const select = source.querySelector("[data-control-choice-input]");
    const selected = select.options[select.selectedIndex];
    source.querySelector("[data-control-cell-value]").textContent = selected.textContent;
    setControlState(source, Boolean(select.value));
    updateAppliedCount(source.closest("[data-filter-grid]"));
  };

  const clearRangeCell = (source) => {
    source.querySelector("[data-control-range-min]").value = "";
    source.querySelector("[data-control-range-max]").value = "";
    source.querySelector("[data-control-cell-value]").textContent = (
      source.dataset.rangeDefaultDisplay || "0–∞"
    );
    setControlState(source, false);
    updateAppliedCount(source.closest("[data-filter-grid]"));
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
      Number(right.dataset.controlDistance || 0)
      - Number(left.dataset.controlDistance || 0)
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
    const gridCells = grid.querySelector("[data-control-grid-cells]");
    const layout = layoutFor(gridCells);
    const sourceLayout = layout.entries.get(source);
    const select = source.querySelector("[data-control-choice-input]");
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

    const trigger = source.querySelector("[data-control-choice-trigger]");
    trigger.setAttribute("aria-expanded", "true");
    const label = source.querySelector(".control-grid-cell-title").textContent;
    const anchor = document.createElement("button");
    anchor.type = "button";
    anchor.className = "control-choice-overlay-cell control-choice-overlay-anchor";
    anchor.dataset.controlChoiceCancel = "true";
    anchor.dataset.controlDistance = "0";
    const anchorLabel = document.createElement("span");
    anchorLabel.textContent = label;
    const anchorInstruction = document.createElement("span");
    anchorInstruction.textContent = "Choose value";
    anchor.append(anchorLabel, anchorInstruction);
    positionOverlayCell(anchor, placement.anchorSlot, layout.columns);

    const optionCells = options.map((option, index) => {
      const button = document.createElement("button");
      const slot = placement.optionSlots[index];
      const distance = Math.abs(slot - placement.anchorSlot);
      button.type = "button";
      button.className = "control-choice-overlay-cell control-choice-overlay-option";
      button.dataset.controlChoiceOption = option.value;
      button.dataset.controlDistance = String(distance);
      button.setAttribute("aria-pressed", option.selected ? "true" : "false");
      button.textContent = `${option.selected ? "✓ " : ""}${option.textContent}`;
      button.style.setProperty(
        "--control-choice-origin",
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

  const makeRangeField = (
    labelText,
    value,
    placeholder,
    key,
    step = "1",
    allowNegative = false,
  ) => {
    const label = document.createElement("label");
    label.className = "control-range-field";
    const title = document.createElement("span");
    title.textContent = labelText;
    const input = document.createElement("input");
    input.type = "number";
    if (!allowNegative) input.min = "0";
    input.step = step;
    input.value = value;
    input.placeholder = placeholder;
    input.dataset[key] = "true";
    label.append(title, input);
    return label;
  };

  const makeRangeHandle = (kind) => {
    const handle = document.createElement("button");
    handle.type = "button";
    handle.className = `control-range-handle control-range-handle-${kind}`;
    handle.dataset.controlRangeHandle = kind;
    const label = document.createElement("span");
    label.className = "control-range-handle-label";
    handle.appendChild(label);
    return handle;
  };

  const rangeValues = (overlay) => {
    const minimumBlank = overlay.minimumEditor.value.trim() === "";
    const maximumBlank = overlay.maximumEditor.value.trim() === "";
    const minimum = minimumBlank
      ? overlay.domainMinimum
      : Math.max(
        overlay.allowNegative ? -Infinity : 0,
        Number(overlay.minimumEditor.value),
      );
    const maximum = maximumBlank
      ? null
      : Math.max(
        overlay.allowNegative ? -Infinity : 0,
        Number(overlay.maximumEditor.value),
      );
    return { maximum, maximumBlank, minimum, minimumBlank };
  };

  const displayRangeNumber = (value, source = null) => {
    if (!Number.isFinite(value)) return "auto";
    return globalThis.CircuitBenchNumber?.format(value, {
      profile: source?.dataset.numberProfile || "default",
    }) ?? String(value);
  };

  const rangeChanged = (overlay) => (
    overlay.minimumEditor.value.trim() !== overlay.originalMinimumValue
    || overlay.maximumEditor.value.trim() !== overlay.originalMaximumValue
  );

  const setHandle = (handle, percent, label, edge) => {
    handle.style.left = `${percent}%`;
    handle.classList.toggle("is-left-edge", edge === "left");
    handle.classList.toggle("is-right-edge", edge === "right");
    handle.querySelector(".control-range-handle-label").textContent = label;
    handle.setAttribute("aria-label", `${label}; drag or use arrow keys to change`);
  };

  const updateRangeOverlay = (overlay) => {
    let { maximum, maximumBlank, minimum, minimumBlank } = rangeValues(overlay);
    if (maximum !== null && minimum > maximum) {
      if (document.activeElement === overlay.minimumEditor || overlay.dragging === "min") {
        minimum = maximum;
        overlay.minimumEditor.value = String(minimum);
      } else {
        maximum = minimum;
        overlay.maximumEditor.value = String(maximum);
      }
    }
    const domainSpan = Math.max(
      overlay.domainMaximum - overlay.domainMinimum,
      Number.EPSILON,
    );
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

    overlay.leftShade.style.width = `${minimumPercent}%`;
    overlay.rightShade.style.left = `${maximumPercent}%`;
    overlay.rightShade.hidden = maximum === null;
    setHandle(
      overlay.minimumHandle,
      minimumPercent,
      `min ${minimumBlank && overlay.autoEmpty
        ? (overlay.source.dataset.rangeEmptyMinimumLabel || "auto")
        : displayRangeNumber(minimum, overlay.source)}`,
      minimumPercent < 8 ? "left" : ""
    );
    setHandle(
      overlay.maximumHandle,
      maximumPercent,
      `max ${maximumBlank
        ? (overlay.autoEmpty
          ? (overlay.source.dataset.rangeEmptyMaximumLabel || "auto")
          : "∞")
        : displayRangeNumber(maximum, overlay.source)}`,
      maximumPercent > 92 ? "right" : ""
    );
    overlay.confirm.hidden = !rangeChanged(overlay);
  };

  const commitRangeOverlay = (overlay, { immediate = false } = {}) => {
    const { maximum, maximumBlank, minimum, minimumBlank } = rangeValues(overlay);
    if (!rangeChanged(overlay)) return;
    overlay.minimumInput.value = overlay.autoEmpty
      ? (minimumBlank ? "" : String(minimum))
      : (minimum > 0 ? String(minimum) : "");
    overlay.maximumInput.value = maximumBlank ? "" : String(maximum);
    const isDefault = !overlay.minimumInput.value && !overlay.maximumInput.value;
    overlay.source.querySelector("[data-control-cell-value]").textContent = isDefault
      ? (overlay.source.dataset.rangeDefaultDisplay || "0–∞")
      : `${minimumBlank
        ? (overlay.source.dataset.rangeEmptyMinimumLabel || "auto")
        : displayRangeNumber(minimum, overlay.source)}–${
        maximumBlank
          ? (overlay.autoEmpty
            ? (overlay.source.dataset.rangeEmptyMaximumLabel || "auto")
            : "∞")
          : displayRangeNumber(maximum, overlay.source)
      }`;
    setControlState(overlay.source, !isDefault);
    updateAppliedCount(overlay.grid);
    const source = overlay.source;
    closeOverlay({ immediate, restoreFocus: true });
    notifyControlCommit(source);
  };

  const openRange = (grid, source) => {
    closeOverlay({ immediate: true });
    const gridCells = grid.querySelector("[data-control-grid-cells]");
    const layout = layoutFor(gridCells);
    const sourceLayout = layout.entries.get(source);
    if (!sourceLayout) return;

    const minimumInput = source.querySelector("[data-control-range-min]");
    const maximumInput = source.querySelector("[data-control-range-max]");
    const trigger = source.querySelector("[data-control-range-trigger]");
    const autoEmpty = source.dataset.rangeAutoEmpty === "true";
    const allowNegative = source.dataset.rangeAllowNegative === "true";
    const rangeStep = source.dataset.rangeStep || "1";
    trigger.setAttribute("aria-expanded", "true");

    const editor = document.createElement("section");
    editor.className = "control-range-overlay";
    editor.dataset.controlDistance = "0";
    editor.style.gridColumn = "1 / -1";
    editor.style.gridRow = String(sourceLayout.row + 1);
    editor.style.setProperty("--control-editor-columns", String(layout.columns));

    const minimumEditor = makeRangeField(
      "Minimum",
      autoEmpty ? minimumInput.value : (minimumInput.value || "0"),
      autoEmpty ? (source.dataset.rangeEmptyMinimumLabel || "auto") : "0",
      "controlRangeMinimumEditor",
      rangeStep,
      allowNegative,
    );
    const maximumEditor = makeRangeField(
      "Maximum",
      maximumInput.value,
      autoEmpty ? (source.dataset.rangeEmptyMaximumLabel || "auto") : "∞",
      "controlRangeMaximumEditor",
      rangeStep,
      allowNegative,
    );
    const histogram = document.createElement("section");
    histogram.className = "control-range-histogram-cell";
    const histogramHead = document.createElement("header");
    const histogramLabel = document.createElement("strong");
    histogramLabel.textContent = source.dataset.histogramLabel;
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "control-range-reset";
    reset.dataset.controlRangeReset = "true";
    reset.textContent = source.dataset.rangeResetLabel || "Reset limits";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "control-range-cancel";
    cancel.dataset.controlRangeCancel = "true";
    cancel.textContent = "Cancel";
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "control-range-confirm";
    confirm.dataset.controlRangeConfirm = "true";
    confirm.textContent = "OK (Enter)";
    confirm.hidden = true;
    const actions = document.createElement("span");
    actions.className = "control-range-actions";
    actions.append(reset, cancel, confirm);
    histogramHead.append(histogramLabel, actions);

    const plot = document.createElement("div");
    plot.className = "control-range-plot";
    plot.setAttribute("role", "img");
    plot.setAttribute(
      "aria-label",
      `${source.dataset.histogramLabel}; draggable minimum and maximum limits`
    );
    const bars = document.createElement("div");
    bars.className = "control-range-bars";
    const counts = source.dataset.histogramCounts.split(",").map(Number);
    const largestCount = Math.max(...counts, 1);
    counts.forEach((count) => {
      const bar = document.createElement("span");
      bar.style.height = `${Math.round((count / largestCount) * 100)}%`;
      bars.appendChild(bar);
    });
    const axisLabels = document.createElement("div");
    axisLabels.className = "control-range-axis-labels";
    const domainMinimum = Number(source.dataset.domainMin);
    const domainMaximum = Number(source.dataset.domainMax);
    [0, 0.25, 0.5, 0.75, 1].forEach((fraction) => {
      const label = document.createElement("span");
      label.style.left = `${fraction * 100}%`;
      label.dataset.edge = fraction === 0 ? "start" : (fraction === 1 ? "end" : "");
      label.textContent = displayRangeNumber(
        domainMinimum + fraction * (domainMaximum - domainMinimum),
        source,
      );
      axisLabels.appendChild(label);
    });
    const leftShade = document.createElement("span");
    leftShade.className = "control-range-shade control-range-shade-left";
    const rightShade = document.createElement("span");
    rightShade.className = "control-range-shade control-range-shade-right";
    const minimumHandle = makeRangeHandle("min");
    const maximumHandle = makeRangeHandle("max");
    plot.append(
      bars,
      leftShade,
      rightShade,
      axisLabels,
      minimumHandle,
      maximumHandle,
    );
    histogram.append(histogramHead, plot);
    editor.append(minimumEditor, maximumEditor, histogram);
    const lockedCells = lockBaseLayout(layout);
    gridCells.appendChild(editor);

    activeOverlay = {
      allowNegative,
      autoEmpty,
      domainMaximum: Number(source.dataset.domainMax),
      domainMinimum: Number(source.dataset.domainMin),
      dragging: null,
      editor,
      elements: [editor],
      confirm,
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
      originalMaximumValue: maximumInput.value.trim(),
      originalMinimumValue: minimumInput.value.trim(),
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
    const unrounded = (
      overlay.domainMinimum
      + ratio * (overlay.domainMaximum - overlay.domainMinimum)
    );
    const configuredStep = overlay.source.dataset.rangeStep || "1";
    const value = configuredStep === "any"
      ? Number(unrounded.toPrecision(5))
      : Math.round(unrounded / Number(configuredStep)) * Number(configuredStep);
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
    setControlState(panel, selected > 0);
    panel.querySelector("[data-tag-rule-label]").textContent = (
      match === "any" ? "any of" : "all of"
    );
    updateAppliedCount(panel.closest("[data-filter-grid]"));
  };

  const resizeTagPanel = (panel) => {
    const gridCells = panel.closest("[data-control-grid-cells]");
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
    updateAppliedCount(grid);
    grid.addEventListener("click", (event) => {
      const clear = event.target.closest("[data-control-clear]");
      if (clear) {
        event.preventDefault();
        event.stopPropagation();
        const source = clear.closest("[data-control-grid-cell]");
        if (activeOverlay?.source === source) closeOverlay({ immediate: true });
        if (source.matches("[data-control-choice-cell]")) {
          const select = source.querySelector("[data-control-choice-input]");
          select.value = "";
          select.dispatchEvent(new Event("change", { bubbles: true }));
          updateChoiceCell(source);
          notifyControlCommit(source);
        } else if (source.matches("[data-control-range-cell]")) {
          clearRangeCell(source);
          notifyControlCommit(source);
        } else if (source.matches("[data-filter-tag-cell]")) {
          const selected = [...source.querySelectorAll(
            '[data-tag-choice] input[type="checkbox"]:checked'
          )];
          selected.forEach((checkbox) => { checkbox.checked = false; });
          selected[0]?.dispatchEvent(new Event("change", { bubbles: true }));
          syncTagPanel(source);
          notifyControlCommit(source);
        } else if (source.matches("[data-filter-related-record-cell]")) {
          source.querySelector("[data-related-record-picker]").dispatchEvent(
            new CustomEvent("control:clear")
          );
        }
        return;
      }
      const option = event.target.closest("[data-control-choice-option]");
      if (option && activeOverlay?.type === "choice") {
        const changed = activeOverlay.select.value !== option.dataset.controlChoiceOption;
        activeOverlay.select.value = option.dataset.controlChoiceOption;
        activeOverlay.select.dispatchEvent(new Event("change", { bubbles: true }));
        updateChoiceCell(activeOverlay.source);
        const source = activeOverlay.source;
        closeOverlay({ restoreFocus: true });
        if (changed) notifyControlCommit(source);
        return;
      }
      if (event.target.closest("[data-control-choice-cancel]")) {
        closeOverlay({ restoreFocus: true });
        return;
      }
      const reset = event.target.closest("[data-control-range-reset]");
      if (reset && activeOverlay?.type === "range") {
        activeOverlay.minimumEditor.value = activeOverlay.autoEmpty ? "" : "0";
        activeOverlay.maximumEditor.value = "";
        updateRangeOverlay(activeOverlay);
        if (activeOverlay.confirm.hidden) {
          closeOverlay({ immediate: true, restoreFocus: true });
        } else {
          commitRangeOverlay(activeOverlay, { immediate: true });
        }
        return;
      }
      const cancel = event.target.closest("[data-control-range-cancel]");
      if (cancel && activeOverlay?.type === "range") {
        closeOverlay({ restoreFocus: true });
        return;
      }
      const confirm = event.target.closest("[data-control-range-confirm]");
      if (confirm && activeOverlay?.type === "range") {
        commitRangeOverlay(activeOverlay);
        return;
      }
      const choiceTrigger = event.target.closest("[data-control-choice-trigger]");
      if (choiceTrigger) {
        openChoice(grid, choiceTrigger.closest("[data-control-choice-cell]"));
        return;
      }
      const rangeTrigger = event.target.closest("[data-control-range-trigger]");
      if (rangeTrigger) {
        openRange(grid, rangeTrigger.closest("[data-control-range-cell]"));
      }
    });

    grid.addEventListener("input", (event) => {
      if (
        activeOverlay?.type === "range"
        && event.target.matches(
          "[data-control-range-minimum-editor], [data-control-range-maximum-editor]"
        )
      ) {
        updateRangeOverlay(activeOverlay);
      }
    });

    grid.addEventListener("pointerdown", (event) => {
      const handle = event.target.closest("[data-control-range-handle]");
      if (!handle || activeOverlay?.type !== "range") return;
      event.preventDefault();
      activeOverlay.dragging = handle.dataset.controlRangeHandle;
    });

    grid.addEventListener("tagpicker:layoutchange", scheduleTagResize);
    grid.addEventListener("control:commit", () => updateAppliedCount(grid));
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
    if (activeOverlay?.type !== "range") return;
    activeOverlay.dragging = null;
  });

  document.addEventListener("keydown", (event) => {
    if (!activeOverlay) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeOverlay({ restoreFocus: true });
      return;
    }
    if (activeOverlay.type === "range" && event.key === "Enter") {
      if (event.target.closest("[data-control-range-reset], [data-control-range-cancel]")) {
        return;
      }
      event.preventDefault();
      commitRangeOverlay(activeOverlay);
      return;
    }
    const handle = event.target.closest("[data-control-range-handle]");
    if (
      activeOverlay.type !== "range"
      || !handle
      || !["ArrowLeft", "ArrowRight"].includes(event.key)
    ) return;
    event.preventDefault();
    const direction = event.key === "ArrowLeft" ? -1 : 1;
    const configuredStep = activeOverlay.source.dataset.rangeStep || "1";
    const baseStep = configuredStep === "any"
      ? Math.max(
        (activeOverlay.domainMaximum - activeOverlay.domainMinimum) / 100,
        Number.EPSILON,
      )
      : Number(configuredStep);
    const step = baseStep * (event.shiftKey ? 10 : 1);
    const values = rangeValues(activeOverlay);
    if (handle.dataset.controlRangeHandle === "min") {
      const ceiling = values.maximum ?? activeOverlay.domainMaximum;
      activeOverlay.minimumEditor.value = String(Math.max(
        activeOverlay.allowNegative ? activeOverlay.domainMinimum : 0,
        Math.min(ceiling, values.minimum + direction * step)
      ));
    } else {
      const current = values.maximum ?? activeOverlay.domainMaximum;
      activeOverlay.maximumEditor.value = String(Math.max(
        values.minimum,
        Math.min(activeOverlay.domainMaximum, current + direction * step)
      ));
    }
    const kind = handle.dataset.controlRangeHandle;
    updateRangeOverlay(activeOverlay);
    requestAnimationFrame(() => activeOverlay?.editor
      .querySelector(`[data-control-range-handle="${kind}"]`)
      ?.focus({ preventScroll: true }));
  });

  const observer = new ResizeObserver(scheduleTagResize);
  grids.forEach((grid) => observer.observe(grid));
  resizeAllTagPanels();
})();
