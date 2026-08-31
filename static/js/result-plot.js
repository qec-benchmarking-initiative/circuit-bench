(() => {
  "use strict";

  const XML_NAMESPACE = "http://www.w3.org/2000/svg";

  function initialisePlot(plot) {
    const tooltip = plot.querySelector("[data-plot-tooltip]");
    const emptySelection = plot.querySelector("[data-plot-selection-empty]");
    const points = Array.from(plot.querySelectorAll(".result-plot-point"));
    const summaries = Array.from(plot.querySelectorAll("[data-plot-summary]"));

    function showTooltip(point, event) {
      if (!tooltip) return;
      tooltip.textContent = point.dataset.hoverLabel || point.getAttribute("aria-label");
      tooltip.hidden = false;
      const bounds = plot.getBoundingClientRect();
      const left = event && "clientX" in event ? event.clientX - bounds.left + 12 : 12;
      const top = event && "clientY" in event ? event.clientY - bounds.top + 12 : 54;
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    }

    function hideTooltip() {
      if (tooltip) tooltip.hidden = true;
    }

    function selectPoint(point) {
      const summaryId = point.dataset.summaryId;
      points.forEach((candidate) => {
        const selected = candidate === point;
        candidate.classList.toggle("is-selected", selected);
        candidate.setAttribute("aria-pressed", selected ? "true" : "false");
      });
      summaries.forEach((summary) => {
        summary.hidden = summary.id !== summaryId;
      });
      if (emptySelection) emptySelection.hidden = true;
    }

    points.forEach((point) => {
      point.setAttribute("aria-pressed", "false");
      point.addEventListener("mouseenter", (event) => showTooltip(point, event));
      point.addEventListener("mousemove", (event) => showTooltip(point, event));
      point.addEventListener("mouseleave", hideTooltip);
      point.addEventListener("focus", (event) => showTooltip(point, event));
      point.addEventListener("blur", hideTooltip);
      point.addEventListener("click", () => selectPoint(point));
      point.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectPoint(point);
        }
      });
    });

    const downloadButton = plot.querySelector("[data-download-plot]");
    downloadButton?.addEventListener("click", () => {
      const source = plot.querySelector("svg.result-plot-svg");
      if (!source) return;
      const clone = source.cloneNode(true);
      clone.setAttribute("xmlns", XML_NAMESPACE);
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
