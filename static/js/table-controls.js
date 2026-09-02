(() => {
  "use strict";

  const parseSort = (value) => value.split(",").map((part) => part.trim()).filter(Boolean);
  const sortKey = (value) => value.startsWith("-") ? value.slice(1) : value;
  const toggled = (value) => value.startsWith("-") ? value.slice(1) : `-${value}`;
  const renderedSort = () => [...document.querySelectorAll("a[data-sort-index]")]
    .sort((a, b) => Number(a.dataset.sortIndex) - Number(b.dataset.sortIndex))
    .map((link) => link.dataset.sortDirection === "desc"
      ? `-${link.dataset.sortKey}`
      : link.dataset.sortKey);

  document.addEventListener("click", (event) => {
    const sortLink = event.target.closest("a[data-sort-key]");
    if (sortLink) {
      event.preventDefault();
      const url = new URL(window.location.href);
      const key = sortLink.dataset.sortKey;
      const encodedSort = parseSort(url.searchParams.get("sort") || "");
      const current = encodedSort.length ? encodedSort : renderedSort();
      let next;
      if (event.shiftKey) {
        const existingIndex = current.findIndex((value) => sortKey(value) === key);
        next = [...current];
        if (existingIndex >= 0) {
          next[existingIndex] = toggled(next[existingIndex]);
        } else {
          next.push(key);
        }
      } else if (current.length && sortKey(current[0]) === key) {
        next = [toggled(current[0])];
      } else {
        next = [key];
      }
      url.searchParams.set("sort", next.join(","));
      url.searchParams.delete("page");
      ["odata", "last_odata", "$filter", "$orderby", "$select", "$top", "$skip", "$count"]
        .forEach((name) => url.searchParams.delete(name));
      window.location.assign(url);
      return;
    }

    const opener = event.target.closest("[data-column-dialog-open]");
    if (opener) {
      document.getElementById(opener.dataset.columnDialogOpen)?.showModal();
    }
  });

  document.querySelectorAll("[data-column-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const checked = [...form.querySelectorAll('input[name="column"]:checked')]
        .map((input) => input.value);
      if (!checked.length) return;
      const url = new URL(window.location.href);
      url.searchParams.set("columns", checked.join(","));
      url.searchParams.delete("page");
      window.location.assign(url);
    });
    form.querySelector("[data-column-reset]")?.addEventListener("click", () => {
      const url = new URL(window.location.href);
      url.searchParams.delete("columns");
      url.searchParams.delete("page");
      window.location.assign(url);
    });
  });
})();
