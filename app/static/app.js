'use strict';
const search = document.querySelector('#object-search');
let activeKind = 'all';
function filterObjects() {
  const query = search.value.toLowerCase();
  let visible = 0;
  document.querySelectorAll('.object-item').forEach(item => {
    item.hidden = !(item.dataset.name.toLowerCase().includes(query) && (activeKind === 'all' || item.dataset.kind === activeKind));
    if (!item.hidden) visible++;
  });
  document.querySelector('#no-matches').hidden = visible > 0;
}
search?.addEventListener('input', filterObjects);
document.querySelectorAll('.filter').forEach(button => button.addEventListener('click', () => {
  activeKind = button.dataset.kind;
  document.querySelectorAll('.filter').forEach(item => item.classList.toggle('active', item === button));
  filterObjects();
}));
document.querySelector('#swap-versions')?.addEventListener('click', () => {
  const left = document.querySelector('#left-version');
  const right = document.querySelector('#right-version');
  [left.value, right.value] = [right.value, left.value];
});
const historyFilters = document.querySelector('#history-filters');
function filterHistory() {
  if (!historyFilters) return;
  const version = document.querySelector('#history-version').value.trim().replace(/^#\s*/, '');
  const change = document.querySelector('#history-change').value.trim().toLowerCase();
  const actor = document.querySelector('#history-actor').value.trim().toLowerCase();
  const from = document.querySelector('#history-date-from').value;
  const to = document.querySelector('#history-date-to').value;
  const status = document.querySelector('#history-status').value;
  const invalidRange = from && to && from > to;
  const rows = document.querySelectorAll('.history-row');
  let visible = 0;
  rows.forEach(row => {
    row.hidden = Boolean(invalidRange) ||
      (version !== '' && row.dataset.version !== version) ||
      !row.dataset.change.toLowerCase().includes(change) ||
      !row.dataset.actor.toLowerCase().includes(actor) ||
      (from !== '' && row.dataset.date < from) ||
      (to !== '' && row.dataset.date > to) ||
      (status !== '' && row.dataset.status !== status);
    if (!row.hidden) visible++;
  });
  document.querySelector('#history-no-matches').hidden = visible > 0;
  document.querySelector('#history-filter-status').textContent = invalidRange
    ? 'Start date must be on or before end date.'
    : `Showing ${visible} of ${rows.length} versions`;
}
historyFilters?.addEventListener('input', filterHistory);
historyFilters?.addEventListener('change', filterHistory);
historyFilters?.addEventListener('submit', event => event.preventDefault());
historyFilters?.addEventListener('reset', () => {
  // The reset event runs before the browser restores the input values.
  window.setTimeout(filterHistory, 0);
});

let copyResetTimer;
document.querySelector('#copy-definition')?.addEventListener('click', async event => {
  const button = event.currentTarget;
  window.clearTimeout(copyResetTimer);
  button.disabled = true;
  try {
    await navigator.clipboard.writeText(document.querySelector('#selected-definition').textContent);
    button.textContent = 'Copied';
  } catch {
    button.textContent = 'Select SQL to copy';
  } finally {
    button.disabled = false;
    copyResetTimer = window.setTimeout(() => {
      button.textContent = 'Copy SQL';
    }, 3000);
  }
});
