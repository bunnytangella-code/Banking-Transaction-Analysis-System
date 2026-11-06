(() => {
  const toggle = document.getElementById("menuToggle");
  const sidebar = document.getElementById("sidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", () => sidebar.classList.toggle("open"));
    document.addEventListener("click", (event) => {
      if (window.innerWidth <= 760 && sidebar.classList.contains("open")
          && !sidebar.contains(event.target) && !toggle.contains(event.target)) {
        sidebar.classList.remove("open");
      }
    });
  }
  const form = document.getElementById("transactionForm");
  const submit = document.getElementById("submitTransaction");
  if (form && submit) {
    form.addEventListener("submit", (event) => {
      if (!form.reportValidity()) {
        event.preventDefault();
        return;
      }
      if (!window.confirm("Record this simulated transaction and update the account balance?")) {
        event.preventDefault();
        return;
      }
      submit.disabled = true;
      submit.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Saving…';
    });
  }
})();
