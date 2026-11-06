(() => {
  const colors = { blue: "#4968df", teal: "#17a789", amber: "#e6ae4b", muted: "#8a96ad" };
  const money = (value) => "₹" + new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 0, maximumFractionDigits: 0
  }).format(value);
  const charts = [];
  function draw(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !window.Chart) return;
    charts.push(new Chart(canvas, config));
  }
  fetch(`/api/dashboard${window.location.search}`, { headers: { Accept: "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error("Analytics could not be loaded.");
      return response.json();
    })
    .then((data) => {
      if (document.getElementById("monthlyChart")) {
        draw("monthlyChart", {
          type: "bar",
          data: { labels: data.monthly.map((row) => row.month), datasets: [
            { label: "Deposits", data: data.monthly.map((row) => row.deposits), backgroundColor: colors.blue, borderRadius: 4, maxBarThickness: 26 },
            { label: "Withdrawals", data: data.monthly.map((row) => row.withdrawals), backgroundColor: colors.teal, borderRadius: 4, maxBarThickness: 26 }
          ] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 7, color: colors.muted, font: { size: 10 } } }, tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${money(item.raw)}` } } },
            scales: { x: { grid: { display: false }, ticks: { color: colors.muted, font: { size: 9 } } }, y: { beginAtZero: true, grid: { color: "#eff1f6" }, ticks: { color: colors.muted, callback: money, font: { size: 9 } } } } }
        });
      }
      if (document.getElementById("typeChart")) {
        draw("typeChart", {
          type: "doughnut",
          data: { labels: data.types.map((row) => row.type), datasets: [{ data: data.types.map((row) => row.total), backgroundColor: [colors.blue, colors.teal], borderWidth: 0, hoverOffset: 4 }] },
          options: { responsive: true, maintainAspectRatio: false, cutout: "70%", plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, color: colors.muted, font: { size: 10 } } }, tooltip: { callbacks: { label: (item) => `${item.label}: ${money(item.raw)}` } } } }
        });
      }
      if (document.getElementById("volumeChart")) {
        draw("volumeChart", {
          type: "line",
          data: { labels: data.volume.map((row) => row.day), datasets: [{ label: "Transactions", data: data.volume.map((row) => row.count), borderColor: colors.blue, backgroundColor: "rgba(73,104,223,.1)", fill: true, tension: .35, pointRadius: 2, pointHoverRadius: 5 }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { color: colors.muted, maxTicksLimit: 7, font: { size: 9 } } }, y: { beginAtZero: true, grid: { color: "#eff1f6" }, ticks: { precision: 0, color: colors.muted, font: { size: 9 } } } } }
        });
      }
      if (document.getElementById("accountChart")) {
        draw("accountChart", {
          type: "bar",
          data: { labels: data.accounts.map((row) => `#${row.account_id} · ${row.customer_name}`), datasets: [{ label: "Transactions", data: data.accounts.map((row) => row.transaction_count), backgroundColor: colors.blue, borderRadius: 4 }] },
          options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { precision: 0, color: colors.muted, font: { size: 9 } }, grid: { color: "#eff1f6" } }, y: { grid: { display: false }, ticks: { color: colors.muted, font: { size: 9 } } } } }
        });
      }
      if (document.getElementById("balanceChart")) {
        draw("balanceChart", {
          type: "bar",
          data: { labels: data.balances.map((row) => `#${row.account_id} · ${row.customer_name}`), datasets: [{ label: "Simulated balance", data: data.balances.map((row) => row.balance), backgroundColor: colors.teal, borderRadius: 4 }] },
          options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (item) => money(item.raw) } } }, scales: { x: { beginAtZero: true, ticks: { color: colors.muted, callback: money, font: { size: 9 } }, grid: { color: "#eff1f6" } }, y: { grid: { display: false }, ticks: { color: colors.muted, font: { size: 9 } } } } }
        });
      }
    })
    .catch((error) => {
      document.querySelectorAll(".chart-wrap").forEach((wrap) => {
        if (!wrap.querySelector("canvas")) return;
        const note = document.createElement("p");
        note.className = "table-empty";
        note.textContent = error.message;
        wrap.append(note);
      });
    });
})();
