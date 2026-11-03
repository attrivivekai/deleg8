// Progressive enhancement for the waitlist form: submit via JSON API when possible.
document.querySelectorAll("form[data-api]").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    const msg = form.querySelector(".form-msg");
    if (window.DELEG8_STATIC) {
      e.preventDefault();
      msg.textContent = "This is a static preview deployment, so signups are disabled here.";
      return;
    }
    e.preventDefault();
    const body = Object.fromEntries(new FormData(form).entries());
    try {
      const res = await fetch(form.dataset.api, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      msg.textContent = res.ok ? "Thanks! You're on the list." : data.detail || "Something went wrong.";
      if (res.ok) form.reset();
    } catch {
      form.submit();
    }
  });
});
