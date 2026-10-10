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
document.querySelector('#copy-definition')?.addEventListener('click', async event => {
  try {
    await navigator.clipboard.writeText(document.querySelector('#selected-definition').textContent);
    event.target.textContent = 'Copied';
  } catch {
    event.target.textContent = 'Select SQL to copy';
  }
});
