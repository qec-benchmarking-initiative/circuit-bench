(() => {
  "use strict";

  // The responsive SVG emits `plot:geometry-change` after its bounds change.

  const XML_NAMESPACE = "http://www.w3.org/2000/svg";
  const AUTOUPDATE_KEY = "circuitBench.plot.autoupdate";
  const AUTOUPDATE_DELAY_MS = 120;
  const submitTimers = new WeakMap();
  const EXPORTED_SVG_PROPERTIES = [
    "color",
    "fill",
    "fill-opacity",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "opacity",
    "paint-order",
    "shape-rendering",
    "stroke",
    "stroke-dasharray",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-opacity",
    "stroke-width",
    "text-anchor",
    "vector-effect",
    "visibility",
  ];

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
      // The plot remains fully usable when storage is unavailable.
    }
  };

  function initialiseAutoUpdate(form) {
    const toggle = form.querySelector("[data-plot-autoupdate-toggle]");
    const updateButton = form.querySelector("[data-plot-update]");
    if (!toggle || !updateButton) return;

    const storedPreference = readStorage(localStorage, AUTOUPDATE_KEY);
    let enabled = storedPreference === null
      ? form.dataset.autoupdateDefault !== "false"
      : storedPreference === "true";
    const manualLabel = updateButton.dataset.manualLabel
      || updateButton.textContent.trim()
      || "Update plot";

    const syncControls = () => {
      toggle.checked = enabled;
      updateButton.disabled = enabled;
      updateButton.textContent = enabled ? "Auto-update enabled" : manualLabel;
    };

    const submitAutomatically = () => {
      if (!enabled) return;
      window.clearTimeout(submitTimers.get(form));
      submitTimers.set(form, window.setTimeout(() => {
        form.requestSubmit();
      }, AUTOUPDATE_DELAY_MS));
    };

    form.addEventListener("change", (event) => {
      if (event.target === toggle) {
        enabled = toggle.checked;
        writeStorage(localStorage, AUTOUPDATE_KEY, String(enabled));
        syncControls();
        if (enabled) submitAutomatically();
        return;
      }
      if (
        event.target.matches("input, select, textarea")
        && !event.target.matches("[data-plot-no-autoupdate]")
      ) {
        submitAutomatically();
      }
    });
    form.addEventListener("input", (event) => {
      if (event.target.matches("[data-plot-live-update]")) submitAutomatically();
    });
    form.addEventListener("control:commit", submitAutomatically);
    syncControls();
  }

  function freezeSvgTheme(source, clone) {
    const sourceElements = [source, ...source.querySelectorAll("*")];
    const cloneElements = [clone, ...clone.querySelectorAll("*")];
    sourceElements.forEach((sourceElement, index) => {
      const cloneElement = cloneElements[index];
      if (!cloneElement?.style) return;
      const computed = window.getComputedStyle(sourceElement);
      EXPORTED_SVG_PROPERTIES.forEach((property) => {
        const value = computed.getPropertyValue(property);
        if (value) cloneElement.style.setProperty(property, value);
      });
    });
  }

  function freezeNeutralSvgTheme(source, clone) {
    const selectedPoints = Array.from(
      source.querySelectorAll(".result-plot-point.is-selected"),
    );
    selectedPoints.forEach((point) => point.classList.remove("is-selected"));
    try {
      freezeSvgTheme(source, clone);
    } finally {
      selectedPoints.forEach((point) => point.classList.add("is-selected"));
    }
  }

  function sanitizeSvgExport(clone) {
    clone.querySelectorAll("[data-plot-export-exclude]").forEach((element) => {
      element.remove();
    });
    clone.classList.remove("is-plot-selecting");
    clone.querySelectorAll(".result-plot-point").forEach((point) => {
      point.classList.remove("is-selected");
      point.removeAttribute("aria-pressed");
    });
  }

  function initialiseResponsiveSvg(plot) {
    const graphic = plot.querySelector(".result-plot-graphic");
    const svg = plot.querySelector("svg.result-plot-svg");
    if (!graphic || !svg) return;

    const baseWidth = Number(svg.dataset.plotWidth);
    const baseHeight = Number(svg.dataset.plotHeight);
    const plotLeft = Number(svg.dataset.plotLeft);
    const basePlotRight = Number(svg.dataset.plotRight);
    if (![baseWidth, baseHeight, plotLeft, basePlotRight].every(Number.isFinite)) return;
    const rightMargin = baseWidth - basePlotRight;
    const basePlotWidth = basePlotRight - plotLeft;

    const resize = () => {
      const measuredWidth = graphic.getBoundingClientRect().width;
      if (!Number.isFinite(measuredWidth) || measuredWidth <= 0) return;
      const width = Math.max(plotLeft + rightMargin + 200, measuredWidth);
      const plotRight = width - rightMargin;
      const projectX = (baseX) => (
        plotLeft + ((baseX - plotLeft) / basePlotWidth) * (plotRight - plotLeft)
      );

      svg.setAttribute("viewBox", `0 0 ${width} ${baseHeight}`);
      svg.dataset.currentPlotRight = String(plotRight);
      svg.querySelector("[data-plot-background]")?.setAttribute("width", String(width));
      svg.querySelector("[data-plot-interaction-surface]")?.setAttribute(
        "width",
        String(plotRight - plotLeft),
      );
      svg.querySelectorAll("[data-plot-extends-right]").forEach((element) => {
        element.setAttribute("x2", String(plotRight));
      });
      svg.querySelectorAll("[data-plot-x]").forEach((element) => {
        const x = projectX(Number(element.dataset.plotX));
        if (!Number.isFinite(x)) return;
        if (element.tagName.toLowerCase() === "g") {
          element.dataset.currentPlotX = String(x);
          element.setAttribute("transform", `translate(${x} ${element.dataset.plotY})`);
          return;
        }
        if (element.hasAttribute("x")) element.setAttribute("x", String(x));
        if (element.hasAttribute("x1")) element.setAttribute("x1", String(x));
        if (element.hasAttribute("x2")) element.setAttribute("x2", String(x));
      });
      svg.querySelectorAll("[data-plot-x-start][data-plot-x-end]").forEach((element) => {
        const start = projectX(Number(element.dataset.plotXStart));
        const end = projectX(Number(element.dataset.plotXEnd));
        if (!Number.isFinite(start) || !Number.isFinite(end)) return;
        if (element.tagName.toLowerCase() === "rect") {
          element.setAttribute("x", String(Math.min(start, end)));
          element.setAttribute("width", String(Math.abs(end - start)));
          return;
        }
        element.setAttribute("x1", String(start));
        element.setAttribute("x2", String(end));
      });
      svg.querySelectorAll("[data-plot-centre-x]").forEach((element) => {
        element.setAttribute("x", String((plotLeft + plotRight) / 2));
      });
      svg.dispatchEvent(new CustomEvent("plot:geometry-change"));
    };

    resize();
    if ("ResizeObserver" in window) {
      const observer = new ResizeObserver(resize);
      observer.observe(graphic);
    } else {
      window.addEventListener("resize", resize);
    }
  }

  const formatPointerValue = (value, unit) => {
    if (!Number.isFinite(value)) return "—";
    const rendered = globalThis.CircuitBenchNumber?.format(value)
      ?? String(Number(value.toPrecision(4)));
    return unit ? `${rendered} ${unit}` : rendered;
  };

  const formNumber = (value) => {
    if (!Number.isFinite(value)) return "";
    return String(Number(value.toPrecision(12)));
  };

  const syncPlotRangeCell = (input) => {
    const cell = input?.closest("[data-control-range-cell]");
    if (!cell) return;
    const minimum = cell.querySelector("[data-control-range-min]")?.value.trim() || "";
    const maximum = cell.querySelector("[data-control-range-max]")?.value.trim() || "";
    const isAuto = !minimum && !maximum;
    cell.classList.toggle("is-explicit", !isAuto);
    const output = cell.querySelector("[data-control-cell-value]");
    if (output) {
      output.textContent = globalThis.CircuitBenchNumber?.formatRange(
        minimum,
        maximum,
        {
          emptyLabel: "Auto",
          minimumFallback: "auto",
          maximumFallback: "auto",
        },
      ) ?? (isAuto ? "Auto" : `${minimum || "auto"}–${maximum || "auto"}`);
    }
  };

  const axesAreExplicit = (form) => [
    "plot_x_min",
    "plot_x_max",
    "plot_y_min",
    "plot_y_max",
  ].some((name) => form.elements.namedItem(name)?.value.trim());

  const syncResetAxesButton = (form) => {
    const button = form.querySelector("[data-reset-plot-axes]");
    if (button) button.disabled = !axesAreExplicit(form);
  };

  const setPlotRanges = (form, values) => {
    Object.entries(values).forEach(([name, value]) => {
      const input = form.elements.namedItem(name);
      if (!input) return;
      input.value = value;
      syncPlotRangeCell(input);
    });
    syncResetAxesButton(form);
    form.dispatchEvent(new CustomEvent("control:commit"));
  };

  const setSvgHidden = (element, hidden) => {
    if (hidden) element.setAttribute("hidden", "");
    else element.removeAttribute("hidden");
  };

  function initialiseCrosshair(svg) {
    if (!svg) return;
    const crosshair = svg.querySelector("[data-plot-crosshair]");
    if (!crosshair) return;
    const vertical = crosshair.querySelector("[data-plot-crosshair-x]");
    const horizontal = crosshair.querySelector("[data-plot-crosshair-y]");
    const readout = crosshair.querySelector("[data-plot-crosshair-readout]");
    const xOutput = crosshair.querySelector("[data-plot-crosshair-x-value]");
    const yOutput = crosshair.querySelector("[data-plot-crosshair-y-value]");
    const pointOutput = crosshair.querySelector("[data-plot-crosshair-point-value]");
    const readoutBox = readout.querySelector("rect");
    const plotLeft = Number(svg.dataset.plotLeft);
    const plotTop = Number(svg.dataset.plotTop);
    const plotBottom = Number(svg.dataset.plotBottom);
    const baseWidth = Number(svg.dataset.plotWidth);
    const baseHeight = Number(svg.dataset.plotHeight);
    const rightMargin = baseWidth - Number(svg.dataset.plotRight);

    const axisValue = (position, start, end, minimum, maximum, scale) => {
      const fraction = Math.max(0, Math.min(1, (position - start) / (end - start)));
      if (scale === "log") {
        const lower = Math.log10(minimum);
        const upper = Math.log10(maximum);
        return 10 ** (lower + fraction * (upper - lower));
      }
      return minimum + fraction * (maximum - minimum);
    };

    const update = (x, y, point = null) => {
      const plotRight = Number(svg.dataset.currentPlotRight)
        || (svg.viewBox.baseVal.width - rightMargin);
      if (x < plotLeft || x > plotRight || y < plotTop || y > plotBottom) {
        setSvgHidden(crosshair, true);
        return;
      }
      vertical.setAttribute("x1", String(x));
      vertical.setAttribute("x2", String(x));
      vertical.setAttribute("y1", String(plotTop));
      vertical.setAttribute("y2", String(plotBottom));
      horizontal.setAttribute("x1", String(plotLeft));
      horizontal.setAttribute("x2", String(plotRight));
      horizontal.setAttribute("y1", String(y));
      horizontal.setAttribute("y2", String(y));

      const xMinimum = Number(svg.dataset.plotXMinimum);
      const xMaximum = Number(svg.dataset.plotXMaximum);
      const yMinimum = Number(svg.dataset.plotYMinimum);
      const yMaximum = Number(svg.dataset.plotYMaximum);
      const xValue = point
        ? Number(point.dataset.plotXValue)
        : axisValue(
          x,
          plotLeft,
          plotRight,
          xMinimum,
          xMaximum,
          svg.dataset.plotXScale,
        );
      const yValue = point
        ? Number(point.dataset.plotYValue)
        : axisValue(
          plotBottom - y,
          0,
          plotBottom - plotTop,
          yMinimum,
          yMaximum,
          svg.dataset.plotYScale,
        );
      xOutput.textContent = `x: ${formatPointerValue(xValue, svg.dataset.plotXUnit)}`;
      yOutput.textContent = `y: ${formatPointerValue(yValue, svg.dataset.plotYUnit)}`;

      const rawPointLabel = point?.dataset.hoverLabel || "";
      pointOutput.style.display = point ? "" : "none";
      pointOutput.textContent = rawPointLabel;
      const maximumWidth = Math.max(176, plotRight - plotLeft - 24);
      const availableTextWidth = maximumWidth - 14;
      const measuredPointWidth = point ? pointOutput.getComputedTextLength() : 0;
      if (point && measuredPointWidth > availableTextWidth) {
        const ratio = availableTextWidth / measuredPointWidth;
        const maximumLabelCharacters = Math.max(
          12,
          Math.floor(rawPointLabel.length * ratio),
        );
        pointOutput.textContent = `${rawPointLabel.slice(0, maximumLabelCharacters - 1)}…`;
      }
      const measuredTextWidth = Math.max(
        xOutput.getComputedTextLength(),
        yOutput.getComputedTextLength(),
        point ? pointOutput.getComputedTextLength() : 0,
      );
      const boxWidth = Math.min(
        maximumWidth,
        Math.max(176, Math.ceil(measuredTextWidth + 14)),
      );
      const boxHeight = point ? 53 : 38;
      readoutBox.setAttribute("width", String(boxWidth));
      readoutBox.setAttribute("height", String(boxHeight));
      const readoutX = x + 12 + boxWidth <= plotRight ? x + 12 : x - boxWidth - 12;
      const readoutY = y - boxHeight - 12 >= plotTop ? y - boxHeight - 12 : y + 12;
      readout.setAttribute("transform", `translate(${readoutX} ${readoutY})`);
      crosshair.classList.toggle("is-snapped", Boolean(point));
      setSvgHidden(crosshair, false);
    };

    svg.addEventListener("pointermove", (event) => {
      const bounds = svg.getBoundingClientRect();
      const x = (event.clientX - bounds.left) * (svg.viewBox.baseVal.width / bounds.width);
      const y = (event.clientY - bounds.top) * (baseHeight / bounds.height);
      const point = event.target.closest(".result-plot-point");
      update(
        point ? Number(point.dataset.currentPlotX || point.dataset.plotX) : x,
        point ? Number(point.dataset.plotY) : y,
        point,
      );
    });
    svg.addEventListener("pointerleave", () => {
      setSvgHidden(crosshair, true);
    });
  }

  function initialiseAxisRangeInteraction(plot, form, svg) {
    if (!form || !svg) return;
    const zoomBox = svg.querySelector("[data-plot-zoom-box]");
    const resetButton = form.querySelector("[data-reset-plot-axes]");
    if (!zoomBox) return;
    let start = null;
    let dragging = false;
    let suppressClick = false;

    const pointerPosition = (event) => {
      const bounds = svg.getBoundingClientRect();
      return {
        x: (event.clientX - bounds.left) * (svg.viewBox.baseVal.width / bounds.width),
        y: (event.clientY - bounds.top) * (svg.viewBox.baseVal.height / bounds.height),
      };
    };
    const plotBounds = () => ({
      left: Number(svg.dataset.plotLeft),
      right: Number(svg.dataset.currentPlotRight || svg.dataset.plotRight),
      top: Number(svg.dataset.plotTop),
      bottom: Number(svg.dataset.plotBottom),
    });
    const insidePlot = (position, bounds) => (
      position.x >= bounds.left && position.x <= bounds.right
      && position.y >= bounds.top && position.y <= bounds.bottom
    );
    const axisValue = (position, startPosition, endPosition, minimum, maximum, scale) => {
      const fraction = Math.max(
        0,
        Math.min(1, (position - startPosition) / (endPosition - startPosition)),
      );
      if (scale === "log") {
        const low = Math.log10(minimum);
        const high = Math.log10(maximum);
        return 10 ** (low + fraction * (high - low));
      }
      return minimum + fraction * (maximum - minimum);
    };
    const updateBox = (position) => {
      const bounds = plotBounds();
      const x = Math.max(bounds.left, Math.min(bounds.right, position.x));
      const y = Math.max(bounds.top, Math.min(bounds.bottom, position.y));
      const left = Math.min(start.x, x);
      const top = Math.min(start.y, y);
      zoomBox.setAttribute("x", String(left));
      zoomBox.setAttribute("y", String(top));
      zoomBox.setAttribute("width", String(Math.abs(x - start.x)));
      zoomBox.setAttribute("height", String(Math.abs(y - start.y)));
      setSvgHidden(zoomBox, false);
      return { x, y };
    };
    const finish = (event) => {
      if (!start) return;
      const end = updateBox(pointerPosition(event));
      const bounds = plotBounds();
      const wasDragging = dragging
        && Math.abs(end.x - start.x) >= 6
        && Math.abs(end.y - start.y) >= 6;
      if (svg.hasPointerCapture?.(event.pointerId)) {
        svg.releasePointerCapture(event.pointerId);
      }
      svg.classList.remove("is-plot-selecting");
      setSvgHidden(zoomBox, true);
      if (wasDragging) {
        event.preventDefault();
        const xMinimum = Number(svg.dataset.plotXMinimum);
        const xMaximum = Number(svg.dataset.plotXMaximum);
        const yMinimum = Number(svg.dataset.plotYMinimum);
        const yMaximum = Number(svg.dataset.plotYMaximum);
        const xStart = axisValue(
          Math.min(start.x, end.x), bounds.left, bounds.right,
          xMinimum, xMaximum, svg.dataset.plotXScale,
        );
        const xEnd = axisValue(
          Math.max(start.x, end.x), bounds.left, bounds.right,
          xMinimum, xMaximum, svg.dataset.plotXScale,
        );
        const yStart = axisValue(
          bounds.bottom - Math.max(start.y, end.y) + bounds.top,
          bounds.top, bounds.bottom,
          yMinimum, yMaximum, svg.dataset.plotYScale,
        );
        const yEnd = axisValue(
          bounds.bottom - Math.min(start.y, end.y) + bounds.top,
          bounds.top, bounds.bottom,
          yMinimum, yMaximum, svg.dataset.plotYScale,
        );
        setPlotRanges(form, {
          plot_x_min: formNumber(Math.min(xStart, xEnd)),
          plot_x_max: formNumber(Math.max(xStart, xEnd)),
          plot_y_min: formNumber(Math.min(yStart, yEnd)),
          plot_y_max: formNumber(Math.max(yStart, yEnd)),
        });
        suppressClick = true;
        window.setTimeout(() => { suppressClick = false; }, 0);
      }
      start = null;
      dragging = false;
    };

    svg.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const position = pointerPosition(event);
      const bounds = plotBounds();
      if (!insidePlot(position, bounds)) return;
      start = position;
      dragging = false;
      zoomBox.setAttribute("x", String(position.x));
      zoomBox.setAttribute("y", String(position.y));
      zoomBox.setAttribute("width", "0");
      zoomBox.setAttribute("height", "0");
    });
    svg.addEventListener("pointermove", (event) => {
      if (!start) return;
      const position = pointerPosition(event);
      if (!dragging && (
        Math.abs(position.x - start.x) >= 4
        || Math.abs(position.y - start.y) >= 4
      )) {
        dragging = true;
        // Capturing on pointerdown can retarget an ordinary point click to the
        // SVG in some browsers. Capture only once this is genuinely a range
        // drag, leaving click targeting untouched.
        svg.setPointerCapture?.(event.pointerId);
        svg.classList.add("is-plot-selecting");
      }
      if (dragging) {
        event.preventDefault();
        updateBox(position);
      }
    });
    svg.addEventListener("pointerup", finish);
    svg.addEventListener("pointercancel", () => {
      start = null;
      dragging = false;
      svg.classList.remove("is-plot-selecting");
      setSvgHidden(zoomBox, true);
    });
    svg.addEventListener("click", (event) => {
      if (!suppressClick) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    }, true);
    resetButton?.addEventListener("click", () => {
      setPlotRanges(form, {
        plot_x_min: "",
        plot_x_max: "",
        plot_y_min: "",
        plot_y_max: "",
      });
    });
    form.addEventListener("control:commit", () => syncResetAxesButton(form));
    syncResetAxesButton(form);
  }

  function initialisePlot(plot) {
    const graphic = plot.querySelector(".result-plot-graphic");
    const emptySelection = plot.querySelector("[data-plot-selection-empty]");
    const points = Array.from(plot.querySelectorAll(".result-plot-point"));
    const summaries = Array.from(plot.querySelectorAll("[data-plot-summary]"));
    initialiseResponsiveSvg(plot);
    if (graphic) initialiseCrosshair(graphic.querySelector("svg.result-plot-svg"));

    const selectionGuides = plot.querySelector("[data-plot-selection-guides]");
    const selectionX = [
      selectionGuides?.querySelector("[data-plot-selection-x]"),
      selectionGuides?.querySelector("[data-plot-selection-halo-x]"),
    ].filter(Boolean);
    const selectionY = [
      selectionGuides?.querySelector("[data-plot-selection-y]"),
      selectionGuides?.querySelector("[data-plot-selection-halo-y]"),
    ].filter(Boolean);
    const summaryById = new Map(summaries.map((summary) => [summary.id, summary]));
    let selectedPoint = null;

    const setSelectionGuidesVisible = (visible) => {
      if (!selectionGuides) return;
      selectionGuides.classList.toggle("is-visible", visible);
    };

    const updateSelectionGuides = () => {
      if (!selectionGuides || !selectedPoint) {
        setSelectionGuidesVisible(false);
        return;
      }
      const svg = selectionGuides.closest("svg");
      const x = Number(selectedPoint.dataset.currentPlotX || selectedPoint.dataset.plotX);
      const y = Number(selectedPoint.dataset.plotY);
      const left = Number(svg.dataset.plotLeft);
      const right = Number(svg.dataset.currentPlotRight || svg.dataset.plotRight);
      const top = Number(svg.dataset.plotTop);
      const bottom = Number(svg.dataset.plotBottom);
      selectionX.forEach((line) => {
        line.setAttribute("x1", String(x));
        line.setAttribute("x2", String(x));
        line.setAttribute("y1", String(top));
        line.setAttribute("y2", String(bottom));
      });
      selectionY.forEach((line) => {
        line.setAttribute("x1", String(left));
        line.setAttribute("x2", String(right));
        line.setAttribute("y1", String(y));
        line.setAttribute("y2", String(y));
      });
      setSelectionGuidesVisible(true);
    };
    selectionGuides?.closest("svg")?.addEventListener(
      "plot:geometry-change",
      updateSelectionGuides,
    );

    function clearSelection() {
      if (selectedPoint) {
        selectedPoint.classList.remove("is-selected");
        selectedPoint.setAttribute("aria-pressed", "false");
        const summary = summaryById.get(selectedPoint.dataset.summaryId);
        if (summary) summary.hidden = true;
        selectedPoint = null;
      }
      if (emptySelection) emptySelection.hidden = false;
      updateSelectionGuides();
    }

    function selectPoint(point) {
      if (selectedPoint && selectedPoint !== point) {
        selectedPoint.classList.remove("is-selected");
        selectedPoint.setAttribute("aria-pressed", "false");
        const previousSummary = summaryById.get(selectedPoint.dataset.summaryId);
        if (previousSummary) previousSummary.hidden = true;
      }
      selectedPoint = point;
      point.classList.add("is-selected");
      point.setAttribute("aria-pressed", "true");
      const summary = summaryById.get(point.dataset.summaryId);
      if (summary) summary.hidden = false;
      if (emptySelection) emptySelection.hidden = true;
      updateSelectionGuides();
    }

    points.forEach((point) => {
      point.setAttribute("aria-pressed", "false");
    });

    graphic?.addEventListener("click", (event) => {
      const point = event.target.closest(".result-plot-point");
      if (point) selectPoint(point);
      else clearSelection();
    });
    plot.addEventListener("keydown", (event) => {
      const point = event.target.closest(".result-plot-point");
      if (point && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        selectPoint(point);
      } else if (event.key === "Escape") {
        clearSelection();
      }
    });

    const controls = plot.querySelector("form[data-plot-controls], form.result-plot-controls");
    if (controls) {
      initialiseAutoUpdate(controls);
      initialiseAxisRangeInteraction(
        plot,
        controls,
        graphic?.querySelector("svg.result-plot-svg"),
      );
    }

    const downloadButton = plot.querySelector("[data-download-plot]");
    downloadButton?.addEventListener("click", () => {
      const source = plot.querySelector("svg.result-plot-svg");
      if (!source) return;
      const clone = source.cloneNode(true);
      clone.setAttribute("xmlns", XML_NAMESPACE);
      freezeNeutralSvgTheme(source, clone);
      sanitizeSvgExport(clone);
      const documentSource = new XMLSerializer().serializeToString(clone);
      const blob = new Blob(
        [`<?xml version="1.0" encoding="UTF-8"?>\n${documentSource}`],
        { type: "image/svg+xml;charset=utf-8" },
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = downloadButton.dataset.filename || "circuit-bench-plot.svg";
      anchor.click();
      URL.revokeObjectURL(url);
    });
  }

  document.querySelectorAll("[data-result-plot]").forEach(initialisePlot);
})();
