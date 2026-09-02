(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const LAYER_ORDER = ["parent", "current", "child"];
  const NODE_HEIGHT = 26;
  const MIN_NODE_WIDTH = 72;
  const LABEL_CHARACTER_WIDTH = 5.4;
  const LABEL_HORIZONTAL_PADDING = 22;
  const NODE_GAP = 14;
  const ROW_GAP = 10;
  const CANVAS_PADDING = 8;
  const BOUNDARY_LANE = 14;
  const LAYER_LABEL_GUTTER = 58;
  const LATERAL_HINT_STEP = 28;

  const svgElement = (name, attributes = {}) => {
    const element = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => {
      element.setAttribute(key, String(value));
    });
    return element;
  };

  const nodeWidth = (node) => Math.max(
    MIN_NODE_WIDTH,
    node.label.length * LABEL_CHARACTER_WIDTH + LABEL_HORIZONTAL_PADDING
  );

  const rowWidth = (nodes) => nodes.reduce(
    (total, node) => total + nodeWidth(node),
    Math.max(0, nodes.length - 1) * NODE_GAP
  );

  const graphLayout = (nodes, width) => {
    const populatedLayers = LAYER_ORDER.filter(
      (layer) => nodes.some((node) => node.layer === layer)
    );
    const hasUpperBoundary = nodes.some(
      (node) => node.hidden_parent_count && node.layer !== "child"
    );
    const hasLowerBoundary = nodes.some(
      (node) => node.hidden_child_count && node.layer !== "parent"
    );
    const topPadding = CANVAS_PADDING + (hasUpperBoundary ? BOUNDARY_LANE : 0);
    const bottomPadding = CANVAS_PADDING + (hasLowerBoundary ? BOUNDARY_LANE : 0);
    const height = topPadding
      + populatedLayers.length * NODE_HEIGHT
      + Math.max(0, populatedLayers.length - 1) * ROW_GAP
      + bottomPadding;
    const positions = new Map();
    const layerYs = [];
    const layerYByName = {};
    populatedLayers.forEach((layer, layerIndex) => {
      const members = nodes.filter((node) => node.layer === layer);
      const layerWidth = rowWidth(members);
      let nextX = (width - layerWidth) / 2;
      const y = topPadding + NODE_HEIGHT / 2
        + layerIndex * (NODE_HEIGHT + ROW_GAP);
      layerYs.push(y);
      layerYByName[layer] = y;
      members.forEach((node) => {
        const width = nodeWidth(node);
        positions.set(node.id, {
          x: nextX + width / 2,
          y,
          width,
          height: NODE_HEIGHT,
        });
        nextX += width + NODE_GAP;
      });
    });
    return {
      height,
      layerYs,
      layerYByName,
      populatedLayers,
      positions,
      hasUpperBoundary,
      hasLowerBoundary,
    };
  };

  const rectangleBoundary = (from, toward) => {
    const dx = toward.x - from.x;
    const dy = toward.y - from.y;
    if (!dx && !dy) return { ...from };
    const scale = 1 / Math.max(
      Math.abs(dx) / (from.width / 2),
      Math.abs(dy) / (from.height / 2)
    );
    return { x: from.x + dx * scale, y: from.y + dy * scale };
  };

  const appendMarker = (defs, id, className) => {
    const marker = svgElement("marker", {
      id,
      viewBox: "0 0 10 10",
      refX: 8.5,
      refY: 5,
      markerWidth: 6,
      markerHeight: 6,
      orient: "auto-start-reverse",
    });
    marker.append(svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", class: className }));
    defs.append(marker);
  };

  const appendEdge = (group, child, parent, markerId, className) => {
    const start = rectangleBoundary(child, parent);
    const end = rectangleBoundary(parent, child);
    group.append(svgElement("line", {
      x1: start.x,
      y1: start.y,
      x2: end.x,
      y2: end.y,
      class: className,
      "marker-end": `url(#${markerId})`,
    }));
  };

  const appendBoundary = (group, position, direction, count, markerId, stub) => {
    const isParent = direction === "parent";
    const start = isParent ? rectangleBoundary(position, stub) : stub;
    const end = isParent ? stub : rectangleBoundary(position, stub);
    group.append(svgElement("line", {
      x1: start.x,
      y1: start.y,
      x2: end.x,
      y2: end.y,
      class: "taxonomy-graph-boundary-edge",
      "marker-end": `url(#${markerId})`,
    }));
    const stubGroup = svgElement("g", { class: "taxonomy-graph-boundary-stub" });
    const title = svgElement("title");
    const relationshipLabel = count === 1
      ? (isParent ? "parent" : "child")
      : (isParent ? "parents" : "children");
    title.textContent = `${count} additional ${relationshipLabel} outside this local view`;
    stubGroup.append(title);
    stubGroup.append(svgElement("rect", {
      x: stub.x - 10,
      y: stub.y - 5,
      width: 20,
      height: 10,
      rx: 2,
    }));
    const text = svgElement("text", { x: stub.x, y: stub.y + 2.5 });
    text.textContent = `+${count}`;
    stubGroup.append(text);
    group.append(stubGroup);
  };

  const boundaryTasks = (graph, positions, layout) => {
    const tasks = [];
    graph.nodes.forEach((node) => {
      const position = positions.get(node.id);
      if (node.hidden_parent_count) {
        tasks.push({
          node,
          position,
          direction: "parent",
          count: node.hidden_parent_count,
          lateral: node.layer === "child",
        });
      }
      if (node.hidden_child_count) {
        tasks.push({
          node,
          position,
          direction: "child",
          count: node.hidden_child_count,
          lateral: node.layer === "parent",
        });
      }
    });

    const focus = positions.get(graph.focus);
    const lateral = tasks
      .filter((task) => task.lateral)
      .sort((first, second) => first.position.x - second.position.x);
    const leftCount = Math.ceil(lateral.length / 2);
    const slots = [];
    for (let index = leftCount; index > 0; index -= 1) {
      slots.push({
        x: focus.x - focus.width / 2 - index * LATERAL_HINT_STEP,
        y: focus.y,
      });
    }
    for (let index = 1; index <= lateral.length - leftCount; index += 1) {
      slots.push({
        x: focus.x + focus.width / 2 + index * LATERAL_HINT_STEP,
        y: focus.y,
      });
    }
    lateral.forEach((task, index) => {
      task.stub = slots[index];
    });

    tasks.filter((task) => !task.lateral).forEach((task) => {
      task.stub = {
        x: task.position.x,
        y: task.direction === "parent" ? 6 : layout.height - 6,
      };
    });
    return tasks;
  };

  const appendNode = (group, node, position) => {
    const link = svgElement("a", {
      href: node.url,
      class: `taxonomy-graph-node taxonomy-graph-node-${node.layer} taxonomy-graph-node-${node.status}`,
      "aria-label": `${node.label}${node.deleted ? ", deleted" : ""}`,
    });
    if (node.colour) link.style.setProperty("--tag-node-colour", node.colour);
    const title = svgElement("title");
    title.textContent = `${node.label}${node.deleted ? " (Deleted)" : ""}`;
    link.append(title);
    link.append(svgElement("rect", {
      x: position.x - position.width / 2,
      y: position.y - NODE_HEIGHT / 2,
      width: position.width,
      height: position.height,
      rx: 2,
    }));
    const label = svgElement("text", {
      x: position.x,
      y: position.y + (node.deleted ? -1 : 3.5),
      "text-anchor": "middle",
      class: "taxonomy-graph-node-label",
    });
    label.textContent = node.label;
    link.append(label);
    if (node.deleted) {
      const deleted = svgElement("text", {
        x: position.x,
        y: position.y + 10,
        "text-anchor": "middle",
        class: "taxonomy-graph-node-deleted-note",
      });
      deleted.textContent = "(Deleted)";
      link.append(deleted);
    }
    group.append(link);
  };

  const renderGraph = (panel) => {
    if (panel.dataset.taxonomyGraphRendered === "true") return;
    const dataElement = document.getElementById(panel.dataset.taxonomyGraphDataId);
    const canvas = panel.querySelector("[data-taxonomy-graph-canvas]");
    if (!dataElement || !canvas) return;
    const graph = JSON.parse(dataElement.textContent);
    const widestLayer = Math.max(
      1,
      ...LAYER_ORDER.map((layer) => rowWidth(
        graph.nodes.filter((node) => node.layer === layer)
      ))
    );
    const lateralHintCount = graph.nodes.filter(
      (node) => (node.layer === "parent" && node.hidden_child_count)
        || (node.layer === "child" && node.hidden_parent_count)
    ).length;
    const focusNode = graph.nodes.find((node) => node.id === graph.focus);
    const lateralHintWidth = nodeWidth(focusNode)
      + 2 * Math.ceil(lateralHintCount / 2) * LATERAL_HINT_STEP
      + LAYER_LABEL_GUTTER * 2;
    const width = Math.max(
      canvas.clientWidth || 420,
      widestLayer + LAYER_LABEL_GUTTER * 2,
      lateralHintWidth
    );
    const layout = graphLayout(graph.nodes, width);
    const svg = svgElement("svg", {
      class: "taxonomy-graph-svg",
      width,
      height: layout.height,
      viewBox: `0 0 ${width} ${layout.height}`,
      role: "img",
      "aria-labelledby": `${panel.id}-title ${panel.id}-description`,
    });
    const title = svgElement("title", { id: `${panel.id}-title` });
    title.textContent = "Local tag taxonomy";
    const description = svgElement("desc", { id: `${panel.id}-description` });
    description.textContent = "Arrows point from child tags to parent tags. Faded boundary arrows indicate relationships outside this local view.";
    svg.append(title, description);

    const defs = svgElement("defs");
    const edgeMarkerId = `${panel.id}-arrow`;
    const boundaryMarkerId = `${panel.id}-boundary-arrow`;
    appendMarker(defs, edgeMarkerId, "taxonomy-graph-arrowhead");
    appendMarker(defs, boundaryMarkerId, "taxonomy-graph-boundary-arrowhead");
    svg.append(defs);

    const guides = svgElement("g", {
      class: "taxonomy-graph-layer-rules",
      "aria-hidden": "true",
    });
    layout.layerYs.slice(0, -1).forEach((y, index) => {
      const nextY = layout.layerYs[index + 1];
      guides.append(svgElement("line", {
        x1: 0,
        y1: (y + nextY) / 2,
        x2: width,
        y2: (y + nextY) / 2,
      }));
    });
    svg.append(guides);

    const layerLabels = svgElement("g", {
      class: "taxonomy-graph-layer-labels",
      "aria-hidden": "true",
    });
    [
      ["parent", "Parents"],
      ["child", "Children"],
    ].forEach(([layer, label]) => {
      if (!layout.populatedLayers.includes(layer)) return;
      const text = svgElement("text", {
        x: 8,
        y: layout.layerYByName[layer] + 3,
      });
      text.textContent = label;
      layerLabels.append(text);
    });
    svg.append(layerLabels);

    const positions = layout.positions;
    const edges = svgElement("g", { "aria-hidden": "true" });
    graph.edges.forEach((edge) => {
      const child = positions.get(edge.child);
      const parent = positions.get(edge.parent);
      if (child && parent) {
        appendEdge(edges, child, parent, edgeMarkerId, "taxonomy-graph-edge");
      }
    });
    boundaryTasks(graph, positions, layout).forEach((task) => {
      appendBoundary(
        edges,
        task.position,
        task.direction,
        task.count,
        boundaryMarkerId,
        task.stub
      );
    });
    svg.append(edges);

    const nodes = svgElement("g");
    graph.nodes.forEach((node) => appendNode(nodes, node, positions.get(node.id)));
    svg.append(nodes);
    canvas.replaceChildren(svg);
    canvas.scrollLeft = Math.max(0, (width - canvas.clientWidth) / 2);
    panel.dataset.taxonomyGraphRendered = "true";
  };

  const clearGraph = (panel) => {
    panel.querySelector("[data-taxonomy-graph-canvas]")?.replaceChildren();
    delete panel.dataset.taxonomyGraphRendered;
  };

  document.querySelectorAll("[data-taxonomy-graph-panel]").forEach((panel) => {
    if (panel.open) renderGraph(panel);
    panel.addEventListener("toggle", () => {
      if (panel.open) {
        requestAnimationFrame(() => renderGraph(panel));
      } else {
        clearGraph(panel);
      }
    });
  });
})();
