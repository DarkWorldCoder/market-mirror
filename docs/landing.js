(() => {
  'use strict';
  // Each tab group owns its panels and supports arrow keys, Home and End.
  document.querySelectorAll('[role="tablist"]').forEach(group => {
    const tabs = Array.from(group.querySelectorAll('[role="tab"]'));
    const select = (tab, focus = false) => {
      tabs.forEach(item => {
        const active = item === tab;
        item.setAttribute('aria-selected', String(active));
        item.tabIndex = active ? 0 : -1;
        document.getElementById(item.getAttribute('aria-controls')).hidden = !active;
      });
      if (focus) tab.focus();
    };
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => select(tab));
      tab.addEventListener('keydown', event => {
        let next;
        if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
        if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = tabs.length - 1;
        if (next !== undefined) {
          event.preventDefault();
          select(tabs[next], true);
        }
      });
    });
  });

  const menuButton = document.querySelector('.menu-toggle');
  const mobileNav = document.getElementById('mobile-nav');
  const closeMenu = () => {
    mobileNav.hidden = true;
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.setAttribute('aria-label', 'Open menu');
  };
  menuButton.addEventListener('click', () => {
    const open = menuButton.getAttribute('aria-expanded') !== 'true';
    mobileNav.hidden = !open;
    menuButton.setAttribute('aria-expanded', String(open));
    menuButton.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  });
  mobileNav.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !mobileNav.hidden) {
      closeMenu();
      menuButton.focus();
    }
  });

  document.querySelectorAll('[data-copy-target]').forEach(button => {
    const label = button.textContent;
    let reset;
    button.addEventListener('click', async () => {
      const status = document.getElementById('copy-status');
      try {
        await navigator.clipboard.writeText(document.getElementById(button.dataset.copyTarget).textContent);
        button.textContent = 'Copied';
        status.textContent = 'Installation instructions copied to clipboard.';
      } catch {
        button.textContent = 'Select to copy';
        status.textContent = 'Clipboard unavailable. Select the visible instructions and copy them manually.';
        const range = document.createRange();
        range.selectNodeContents(document.getElementById(button.dataset.copyTarget));
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
      clearTimeout(reset);
      reset = setTimeout(() => { button.textContent = label; }, 2400);
    });
  });

  const dialog = document.getElementById('film-dialog');
  const film = dialog.querySelector('video');
  document.querySelectorAll('.film-trigger').forEach(link => {
    link.addEventListener('click', event => {
      if (typeof dialog.showModal !== 'function') return;
      event.preventDefault();
      dialog.showModal();
    });
  });
  dialog.querySelector('.dialog-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => film.pause());
  dialog.addEventListener('click', event => {
    if (event.target === dialog) {
      const bounds = dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    }
  });
})();
