(() => {
  'use strict';
  const button = document.getElementById('copy-template');
  const template = document.getElementById('experiment-template');
  const status = document.getElementById('template-status');
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(template.textContent);
      status.textContent = 'Experiment template copied. Replace the example with your own product facts.';
    } catch {
      const range = document.createRange();
      range.selectNodeContents(template);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      status.textContent = 'Clipboard unavailable. The template is selected for manual copying; you can also download it.';
    }
  });
})();
