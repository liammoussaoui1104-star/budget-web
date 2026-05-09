// ── Sidebar (hamburger) ────────────────────────────────────────────────────
(function() {
  const hamburger = document.getElementById('hamburger');
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebarOverlay');
  const closeBtn = document.getElementById('sidebarClose');

  function openSidebar() {
    sidebar && sidebar.classList.add('open');
    overlay && overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
  function closeSidebar() {
    sidebar && sidebar.classList.remove('open');
    overlay && overlay.classList.remove('open');
    document.body.style.overflow = '';
  }

  hamburger && hamburger.addEventListener('click', openSidebar);
  closeBtn && closeBtn.addEventListener('click', closeSidebar);
  overlay && overlay.addEventListener('click', closeSidebar);
})();

// ── Period navigation ──────────────────────────────────────────────────────
(function() {
  document.querySelectorAll('.period-nav').forEach(link => {
    link.addEventListener('click', async e => {
      e.preventDefault();
      const y = link.dataset.y;
      const m = link.dataset.m;
      await fetch(`/api/period?y=${y}&m=${m}`);
      location.reload();
    });
  });
})();

// ── Flash auto-dismiss ─────────────────────────────────────────────────────
(function() {
  setTimeout(() => {
    document.querySelectorAll('.flash').forEach(el => {
      el.style.transition = 'opacity .5s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 500);
    });
  }, 4000);
})();
