document.addEventListener("DOMContentLoaded", () => {
    const plans = JSON.parse(document.getElementById("renewal-plans").textContent);
    const plan = document.getElementById("id_payment_plan"), custom = document.getElementById("id_is_custom_plan");
    const amount = document.getElementById("id_custom_amount"), months = document.getElementById("id_custom_duration_months");
    const start = document.getElementById("id_start_date"), end = document.getElementById("id_end_date");
    function calculateEnd() {
        const duration = Number(months.value);
        if (!start.value || !Number.isInteger(duration) || duration <= 0) return;
        const parts = start.value.split("-").map(Number);
        const date = new Date(parts[0], parts[1] - 1 + duration, 1, 12);
        const lastDay = new Date(date.getFullYear(), date.getMonth() + 1, 0, 12).getDate();
        date.setDate(Math.min(parts[2], lastDay));
        if (!Number.isFinite(date.getTime()) || date.getFullYear() > 9999) return;
        end.value = date.getFullYear() + "-" + String(date.getMonth()+1).padStart(2,"0") + "-" + String(date.getDate()).padStart(2,"0");
    }
    function update(recalculate) {
        plan.disabled = custom.checked;
        plan.required = !custom.checked;
        amount.disabled = months.disabled = !custom.checked;
        amount.required = months.required = custom.checked;
        if (!custom.checked) {
            const selected = plans.find(item => String(item.id) === plan.value);
            amount.value = selected ? selected.amount : "";
            months.value = selected ? selected.months : "";
        }
        if (recalculate) calculateEnd();
    }
    custom.addEventListener("change", () => update(true));
    plan.addEventListener("change", () => update(true));
    months.addEventListener("input", calculateEnd);
    start.addEventListener("change", calculateEnd);
    update(!end.value);
});
