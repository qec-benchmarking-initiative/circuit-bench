(() => {
  "use strict";

  document.querySelectorAll("[data-previous-schema-control]").forEach((control) => {
    const form = control.closest("form");
    const schemaInput = control.querySelector(
      'input[name="hyperparameter_schema_artifact"]'
    );
    const upload = control.querySelector("[data-submission-file-upload]");
    const button = control.querySelector("[data-use-previous-schema]");
    const status = control.querySelector("[data-previous-schema-status]");
    const choices = new Map(
      [...control.querySelectorAll("[data-previous-version-id]")].map((item) => [
        item.dataset.previousVersionId,
        { id: item.dataset.schemaId, label: item.dataset.schemaLabel },
      ])
    );
    const previousName = control.dataset.previousVersionInput;
    let previousId = form.querySelector(`input[name="${previousName}"]`)?.value || "";

    const selectedPreviousId = () =>
      form.querySelector(`input[name="${previousName}"]`)?.value || "";

    const render = ({ reset = false } = {}) => {
      const nextPreviousId = selectedPreviousId();
      const choice = choices.get(nextPreviousId);
      if (reset || nextPreviousId !== previousId) schemaInput.value = "";
      previousId = nextPreviousId;
      button.disabled = !choice;
      if (schemaInput.value && choice?.id === schemaInput.value) {
        status.textContent = `Selected: ${choice.label}.`;
      } else if (!nextPreviousId) {
        status.textContent = "Choose a previous decoder revision first.";
      } else if (!choice) {
        status.textContent = "The selected previous revision has no schema file.";
      } else {
        status.textContent = `Available: ${choice.label}.`;
      }
    };

    form.addEventListener("filterquery:change", () => render());
    button.addEventListener("click", () => {
      const choice = choices.get(selectedPreviousId());
      if (!choice) return;
      schemaInput.value = choice.id;
      upload.value = "";
      render();
    });
    upload.addEventListener("change", () => {
      if (!upload.files.length) return render();
      schemaInput.value = "";
      status.textContent = `New file selected: ${upload.files[0].name}.`;
    });
    render();
  });
})();
