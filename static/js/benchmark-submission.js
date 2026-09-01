(() => {
  const form = document.querySelector("[data-benchmark-submission]");
  if (!form) return;
  const input = form.querySelector("[name=items_json]");
  const tableBody = form.querySelector("[data-benchmark-items]");
  const dialog = document.querySelector("[data-circuit-picker]");
  const optionsBody = dialog.querySelector("[data-circuit-options]");
  const search = dialog.querySelector("[data-circuit-search]");
  const circuits = JSON.parse(document.getElementById("benchmark-circuit-options").textContent);
  let selected;
  try { selected = JSON.parse(input.value || "[]"); } catch (_error) { selected = []; }

  const byId = new Map(circuits.map((item) => [item.id, item]));
  const save = () => { input.value = JSON.stringify(selected); };
  const button = (label, action, disabled = false) => {
    const element = document.createElement("button");
    element.type = "button";
    element.className = "table-action";
    element.textContent = label;
    element.disabled = disabled;
    element.addEventListener("click", action);
    return element;
  };
  const renderSelected = () => {
    tableBody.replaceChildren();
    if (!selected.length) {
      const row = tableBody.insertRow(); const cell = row.insertCell();
      cell.colSpan = 5; cell.className = "table-empty"; cell.textContent = "No circuits selected.";
      save(); return;
    }
    selected.forEach((entry, index) => {
      const circuit = byId.get(entry.circuit_revision);
      const row = tableBody.insertRow();
      row.insertCell().textContent = String(index + 1);
      row.insertCell().textContent = circuit ? circuit.name : entry.circuit_revision;
      const requirement = document.createElement("select");
      requirement.innerHTML = '<option value="required">Required</option><option value="optional">Optional</option>';
      requirement.value = entry.required ? "required" : "optional";
      requirement.addEventListener("change", () => { entry.required = requirement.value === "required"; save(); });
      row.insertCell().append(requirement);
      const order = row.insertCell();
      order.append(button("↑", () => { [selected[index - 1], selected[index]] = [selected[index], selected[index - 1]]; renderSelected(); }, index === 0));
      order.append(" ", button("↓", () => { [selected[index], selected[index + 1]] = [selected[index + 1], selected[index]]; renderSelected(); }, index === selected.length - 1));
      row.insertCell().append(button("Remove", () => { selected.splice(index, 1); renderSelected(); renderOptions(); }));
    });
    save();
  };
  const renderOptions = () => {
    const query = search.value.trim().toLocaleLowerCase();
    optionsBody.replaceChildren();
    circuits.filter((item) => !selected.some((entry) => entry.circuit_revision === item.id))
      .filter((item) => !query || `${item.name} ${item.slug}`.toLocaleLowerCase().includes(query))
      .forEach((item) => {
        const row = optionsBody.insertRow(); row.insertCell().textContent = item.name; row.insertCell().textContent = item.slug;
        const actions = row.insertCell();
        actions.append(button("Add required", () => { selected.push({circuit_revision:item.id, required:true}); renderSelected(); renderOptions(); }));
        actions.append(" ", button("Add optional", () => { selected.push({circuit_revision:item.id, required:false}); renderSelected(); renderOptions(); }));
      });
  };
  form.querySelector("[data-open-circuit-picker]").addEventListener("click", () => { renderOptions(); dialog.showModal(); search.focus(); });
  dialog.querySelector("[data-close-circuit-picker]").addEventListener("click", () => dialog.close());
  search.addEventListener("input", renderOptions);
  renderSelected();
})();
