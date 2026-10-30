// Apply the saved theme before first paint to avoid a flash. Loaded as a same-origin file so the
// Content-Security-Policy can stay free of inline scripts.
try {
  var t = localStorage.getItem('rf-theme')
  if (t !== 'light' && t !== 'dark') {
    t = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  document.documentElement.dataset.theme = t
} catch (e) {}
