(() => {
  const kind = document.getElementById('id_report_type');
  if (!kind) return;
  const form = kind.form;
  const groups = form.querySelectorAll('[data-period-modes]');
  function refresh() {
    for (const group of groups) {
      const visible = group.dataset.periodModes.split(' ').includes(kind.value);
      group.hidden = !visible;
      for (const control of group.querySelectorAll('input, select')) {
        control.disabled = !visible;
      }
    }
  }
  kind.addEventListener('change', refresh);
  window.addEventListener('pageshow', refresh);
  form.addEventListener('submit', refresh);
  refresh();

  const donor = document.getElementById('id_donor');
  if (!donor) return;
  const $ = window.django?.jQuery || window.jQuery;
  if (!$?.fn.select2) return;
  $(donor).select2({
    dir: 'rtl',
    width: '100%',
    placeholder: 'ابحث باسم الكافل',
    allowClear: !donor.required,
    minimumResultsForSearch: 0,
    language: { noResults: () => 'لا توجد نتائج مطابقة' }
  }).on('select2:open', () => {
    const search = document.querySelector('.select2-container--open .select2-search__field');
    if (search) {
      search.setAttribute('aria-label', 'ابحث باسم الكافل');
      search.focus();
    }
  });
})();
