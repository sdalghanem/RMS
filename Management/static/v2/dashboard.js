(() => {
  const period = document.getElementById('fd-period');
  const custom = document.getElementById('fd-custom');
  if (!period || !custom) return;
  const update = () => {
    const active = period.value === 'custom';
    custom.hidden = !active;
    custom.querySelectorAll('input').forEach(input => {input.disabled = !active;input.required = active;});
  };
  period.addEventListener('change', update);
  update();
})();
