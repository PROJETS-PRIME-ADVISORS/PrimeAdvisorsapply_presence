const loginView = document.getElementById('login-view');
const dashboardView = document.getElementById('dashboard-view');
const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');
const tableBody = document.getElementById('table-body');
const dateFilter = document.getElementById('date-filter');
const exportLink = document.getElementById('export-link');

async function checkStatus() {
  const response = await fetch('/admin/status');
  const data = await response.json();
  if (data.is_admin) showDashboard();
}

function showDashboard() {
  loginView.classList.add('hidden');
  dashboardView.classList.remove('hidden');
  loadPointages();
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const password = document.getElementById('password').value;
  const response = await fetch('/admin/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (response.ok) {
    loginError.classList.add('hidden');
    showDashboard();
  } else {
    loginError.textContent = 'Mot de passe incorrect.';
    loginError.classList.remove('hidden');
  }
});

document.getElementById('logout-btn').addEventListener('click', async () => {
  await fetch('/admin/logout', { method: 'POST' });
  dashboardView.classList.add('hidden');
  loginView.classList.remove('hidden');
});

document.getElementById('filter-btn').addEventListener('click', () => loadPointages(dateFilter.value));
document.getElementById('reset-btn').addEventListener('click', () => {
  dateFilter.value = '';
  loadPointages();
});

async function loadPointages(date) {
  const url = date ? `/api/pointages?date=${date}` : '/api/pointages';
  const response = await fetch(url);
  const rows = await response.json();

  tableBody.innerHTML = '';
  rows.forEach((r) => {
    const tr = document.createElement('tr');
    const badgeClass = r.source === 'manuel' ? 'manuel' : 'auto';
    const badgeLabel = r.source === 'manuel' ? 'Historique' : 'QR';
    tr.innerHTML = `
      <td>${escapeHtml(r.nom)}</td>
      <td>${escapeHtml(r.prenom)}</td>
      <td>${r.date}</td>
      <td>${r.heure_arrivee || '—'}</td>
      <td>${r.heure_depart || '—'}</td>
      <td class="motif-cell">${r.motif ? escapeHtml(r.motif) : '—'}</td>
      <td><span class="badge ${badgeClass}">${badgeLabel}</span></td>
    `;
    tableBody.appendChild(tr);
  });

  exportLink.href = date ? `/api/export?date=${date}` : '/api/export';
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

const importPanel = document.getElementById('import-panel');
const importRows = document.getElementById('import-rows');
const importFeedback = document.getElementById('import-feedback');

document.getElementById('toggle-import-btn').addEventListener('click', () => {
  importPanel.classList.toggle('hidden');
  if (!importPanel.classList.contains('hidden') && importRows.children.length === 0) {
    for (let i = 0; i < 3; i += 1) addImportRow();
  }
});

document.getElementById('add-row-btn').addEventListener('click', addImportRow);

function addImportRow() {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><input type="text" class="f-nom"></td>
    <td><input type="text" class="f-prenom"></td>
    <td><input type="date" class="f-date"></td>
    <td><input type="text" class="f-arrivee" placeholder="08:00"></td>
    <td><input type="text" class="f-depart" placeholder="17:00"></td>
    <td><input type="text" class="f-motif" placeholder="facultatif"></td>
  `;
  importRows.appendChild(tr);
}

document.getElementById('submit-import-btn').addEventListener('click', async () => {
  const entries = [...importRows.querySelectorAll('tr')]
    .map((tr) => ({
      nom: tr.querySelector('.f-nom').value.trim(),
      prenom: tr.querySelector('.f-prenom').value.trim(),
      date: tr.querySelector('.f-date').value.trim(),
      heure_arrivee: tr.querySelector('.f-arrivee').value.trim(),
      heure_depart: tr.querySelector('.f-depart').value.trim(),
      motif: tr.querySelector('.f-motif').value.trim(),
    }))
    .filter((e) => e.nom || e.prenom || e.date || e.heure_arrivee || e.heure_depart || e.motif);

  if (entries.length === 0) {
    importFeedback.innerHTML = '<span class="ko">Aucune ligne à importer.</span>';
    return;
  }

  const response = await fetch('/api/pointages/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entries }),
  });
  const data = await response.json();

  if (!response.ok) {
    importFeedback.innerHTML = `<span class="ko">${data.error || "Erreur lors de l'import."}</span>`;
    return;
  }

  const parts = [];
  if (data.inserted.length) {
    parts.push(`<span class="ok">${data.inserted.length} ligne(s) importée(s).</span>`);
  }
  if (data.skipped.length) {
    const details = data.skipped.map((s) => `ligne ${s.ligne} : ${s.raison}`).join('<br>');
    parts.push(`<span class="ko">${data.skipped.length} ligne(s) ignorée(s) —<br>${details}</span>`);
  }
  importFeedback.innerHTML = parts.join('<br><br>');

  importRows.innerHTML = '';
  for (let i = 0; i < 3; i += 1) addImportRow();
  loadPointages(dateFilter.value || undefined);
});

checkStatus();
