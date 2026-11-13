// Light or dark. Runs in <head> so the right theme is set before the page paints. The choice is kept
// in this browser only; without one, the computer's own setting decides.
'use strict';
(() => {
  let saved = null;
  try { saved = localStorage.getItem('theme'); } catch (error) { /* private window: no storage */ }
  const system = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  document.documentElement.dataset.theme = saved === 'dark' || saved === 'light' ? saved : system;
})();
