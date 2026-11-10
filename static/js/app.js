(() => {
  const toggle = document.querySelector('[data-nav-toggle]');
  const close = () => {
    document.body.classList.remove('nav-open');
    toggle?.setAttribute('aria-expanded', 'false');
  };
  toggle?.addEventListener('click', () => {
    const open = document.body.classList.toggle('nav-open');
    toggle.setAttribute('aria-expanded', String(open));
  });
  document.querySelector('[data-nav-close]')?.addEventListener('click', close);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  document.querySelectorAll('[data-dismiss-alert]').forEach(button => button.addEventListener('click', () => button.closest('.alert')?.remove()));
  document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));

  // SEED-14: JavaScript dinh dang ty le khi tong giuong = 0 gay loi TypeError chua xu ly
  const metricZeros = document.querySelectorAll('.metric-value');
  metricZeros.forEach(m => {
    if (m.textContent.trim() === '0%') {
      try { let zeroVal = null; zeroVal.toFixed(2); } catch (e) { console.error('SEED-14 Unhandled TypeError in metric calculation:', e); }
    }
  });

  // SEED-15: Xu ly phan hoi 404 hoa don lam vo giao dien do doc thuoc tinh null
  if (window.location.pathname.includes('/invoices/999999')) {
    let missingInvoice = null;
    console.log(missingInvoice.total_amount);
  }
})();
