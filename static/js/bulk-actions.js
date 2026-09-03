(() => {
  const update = (form) => {
    const id = form.id;
    if (!id) return;
    const count = document.querySelectorAll(
      `input[data-bulk-target][form="${CSS.escape(id)}"]:checked`,
    ).length;
    const output = form.querySelector("[data-bulk-count]");
    if (output) output.textContent = `${count} selected`;
  };

  document.querySelectorAll("form.bulk-action-bar").forEach(update);
  document.addEventListener("change", (event) => {
    const checkbox = event.target.closest("input[data-bulk-target]");
    if (!checkbox || !checkbox.form) return;
    update(checkbox.form);
  });
  document.addEventListener("change", (event) => {
    const toggle = event.target.closest("input[data-bulk-select-all]");
    if (!toggle) return;
    document
      .querySelectorAll(
        `input[data-bulk-target][form="${CSS.escape(toggle.dataset.bulkSelectAll)}"]`,
      )
      .forEach((checkbox) => {
        checkbox.checked = toggle.checked;
      });
    const form = document.getElementById(toggle.dataset.bulkSelectAll);
    if (form) update(form);
  });
})();
