(() => {
  const kind = document.getElementById('id_report_type');
  if (!kind) return;
  const refresh = () => {
    const active = {year: kind.value !== 'custom', quarter: kind.value === 'quarterly',
      half: kind.value === 'half', from_date: kind.value === 'custom', to_date: kind.value === 'custom'};
    Object.entries(active).forEach(([name, visible]) => {
      const wrap = document.querySelector(`[data-field="${name}"]`);
      if (!wrap) return;
      wrap.hidden = !visible;
      wrap.querySelectorAll('input, select').forEach(input => { input.disabled = !visible; });
    });
  };
  kind.addEventListener('change', refresh);
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
