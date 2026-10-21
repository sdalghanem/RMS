document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-invoice-number-url]").forEach(status => {
        const input = document.getElementById(status.dataset.inputId);
        if (!input) return;
        let timer, controller, version = 0;
        const show = (text, color) => { status.textContent = text; status.className = "small mt-1 " + color; };
        const check = () => {
            clearTimeout(timer);
            if (controller) controller.abort();
            const current = ++version, number = input.value.trim();
            show("", "");
            if (!number) return;
            show("جاري التحقق…", "text-muted");
            timer = setTimeout(async () => {
                controller = new AbortController();
                try {
                    const url = new URL(status.dataset.invoiceNumberUrl, location.origin);
                    url.searchParams.set("number", number);
                    const response = await fetch(url, {signal: controller.signal, credentials: "same-origin", cache: "no-store"});
                    if (!response.ok) throw new Error("unavailable");
                    const data = await response.json();
                    if (current !== version) return;
                    if (typeof data.available !== "boolean") throw new Error("invalid response");
                    show(data.available ? "✓ رقم السند متاح" : "× رقم السند مستخدم مسبقًا", data.available ? "text-success" : "text-danger");
                } catch (error) {
                    if (current === version && error.name !== "AbortError") show("تعذر التحقق", "text-warning");
                }
            }, 400);
        };
        input.addEventListener("input", check);
        input.addEventListener("change", check);
        if (input.value) check();
    });
});
