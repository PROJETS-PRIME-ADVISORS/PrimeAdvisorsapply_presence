const TIMEZONE = 'Africa/Abidjan';

const loginView = document.getElementById('login-view');
const dashboardView = document.getElementById('dashboard-view');
const loginForm = document.getElementById('login-form');
const passwordInput = document.getElementById('password');
const loginError = document.getElementById('login-error');
const tableBody = document.getElementById('table-body');
const tableSummary = document.getElementById('table-summary');
const dateFilter = document.getElementById('date-filter');
const exportLink = document.getElementById('export-link');

async function api(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    return { ok: false, status: 0, data: { error: 'Impossible de contacter le serveur.' } };
  }
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, data };
}

function postJson(url, body) {
  return api(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

async function checkStatus() {
  const { data } = await api('/admin/status');
  if (data.is_admin) showDashboard();
}

function showDashboard() {
  loginView.classList.add('hidden');
  dashboardView.classList.remove('hidden');
  dateFilter.value = today();
  loadPointages();
}

function showLogin(message) {
  dashboardView.classList.add('hidden');
  loginView.classList.remove('hidden');
  if (message) showLoginError(message);
}

function showLoginError(message) {
  loginError.textContent = message;
  loginError.classList.remove('hidden');
}

function today() {
  // « en-CA » donne la date au format AAAA-MM-JJ, celui qu'attend le champ date.
  return new Date().toLocaleDateString('en-CA', { timeZone: TIMEZONE });
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = loginForm.querySelector('button');
  button.disabled = true;
  const { ok, data } = await postJson('/admin/login', { password: passwordInput.value });
  button.disabled = false;

  if (ok) {
    passwordInput.value = '';
    loginError.classList.add('hidden');
    showDashboard();
  } else {
    showLoginError(data.error || 'Connexion impossible.');
  }
});

document.getElementById('logout-btn').addEventListener('click', async () => {
  await postJson('/admin/logout');
  showLogin();
});

dateFilter.addEventListener('change', () => loadPointages());
document.getElementById('today-btn').addEventListener('click', () => {
  dateFilter.value = today();
  loadPointages();
});
document.getElementById('reset-btn').addEventListener('click', () => {
  dateFilter.value = '';
  loadPointages();
});

async function loadPointages() {
  const date = dateFilter.value;
  const query = date ? `?${new URLSearchParams({ date })}` : '';
  exportLink.href = `/api/export${query}`;

  const { ok, status, data } = await api(`/api/pointages${query}`);
  if (status === 401) {
    showLogin('Session expirée : reconnectez-vous.');
    return;
  }
  if (!ok) {
    tableSummary.textContent = '';
    showMessageRow(data.error || 'Chargement impossible.');
    return;
  }
  showRows(data);
}

function showRows(rows) {
  if (rows.length === 0) {
    tableSummary.textContent = '';
    showMessageRow(dateFilter.value ? 'Aucun pointage à cette date.' : 'Aucun pointage enregistré.');
    return;
  }

  tableBody.replaceChildren(...rows.map((r) => {
    const tr = document.createElement('tr');
    [r.nom, r.prenom, r.date, r.heure_arrivee || '—', r.heure_depart || '—'].forEach((valeur) => tr.append(cell(valeur)));

    const motif = cell(r.motif || '—');
    motif.className = 'motif-cell';
    tr.append(motif);

    const badge = document.createElement('span');
    badge.className = `badge ${r.source === 'manuel' ? 'manuel' : 'auto'}`;
    badge.textContent = r.source === 'manuel' ? 'Historique' : 'QR';
    const origine = document.createElement('td');
    origine.append(badge);
    tr.append(origine);
    return tr;
  }));

  const sansDepart = rows.filter((r) => !r.heure_depart).length;
  tableSummary.textContent = sansDepart
    ? `${rows.length} pointage(s), dont ${sansDepart} sans départ enregistré.`
    : `${rows.length} pointage(s).`;
}

function cell(valeur) {
  const td = document.createElement('td');
  td.textContent = valeur;
  return td;
}

function showMessageRow(message) {
  const td = cell(message);
  td.className = 'empty';
  td.colSpan = 7;
  const tr = document.createElement('tr');
  tr.append(td);
  tableBody.replaceChildren(tr);
}

const importPanel = document.getElementById('import-panel');
const importRows = document.getElementById('import-rows');
const importFeedback = document.getElementById('import-feedback');
const submitImportBtn = document.getElementById('submit-import-btn');

document.getElementById('toggle-import-btn').addEventListener('click', () => {
  importPanel.classList.toggle('hidden');
  if (!importPanel.classList.contains('hidden') && importRows.children.length === 0) {
    addImportRows(3);
  }
});

document.getElementById('add-row-btn').addEventListener('click', () => addImportRow());

function addImportRows(nombre) {
  for (let i = 0; i < nombre; i += 1) addImportRow();
}

function addImportRow() {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><input type="text" class="f-nom" maxlength="80" autocapitalize="characters" spellcheck="false"></td>
    <td><input type="text" class="f-prenom" maxlength="80" autocapitalize="words" spellcheck="false"></td>
    <td><input type="date" class="f-date" max="${today()}"></td>
    <td><input type="time" class="f-arrivee"></td>
    <td><input type="time" class="f-depart"></td>
    <td><input type="text" class="f-motif" maxlength="300" placeholder="facultatif"></td>
  `;
  importRows.appendChild(tr);
  return tr;
}

submitImportBtn.addEventListener('click', async () => {
  const lignes = [...importRows.querySelectorAll('tr')].map((tr) => ({
    tr,
    entry: {
      nom: tr.querySelector('.f-nom').value.trim(),
      prenom: tr.querySelector('.f-prenom').value.trim(),
      date: tr.querySelector('.f-date').value.trim(),
      heure_arrivee: tr.querySelector('.f-arrivee').value.trim(),
      heure_depart: tr.querySelector('.f-depart').value.trim(),
      motif: tr.querySelector('.f-motif').value.trim(),
    },
  })).filter(({ entry }) => Object.values(entry).some((valeur) => valeur !== ''));

  lignes.forEach(({ tr }) => tr.classList.remove('row-error'));

  if (lignes.length === 0) {
    showFeedback([['ko', 'Aucune ligne à importer.']]);
    return;
  }

  submitImportBtn.disabled = true;
  const { ok, status, data } = await postJson('/api/pointages/import', { entries: lignes.map((l) => l.entry) });
  submitImportBtn.disabled = false;

  if (status === 401) {
    showLogin('Session expirée : reconnectez-vous.');
    return;
  }
  if (!ok) {
    showFeedback([['ko', data.error || "Erreur lors de l'import."]]);
    return;
  }

  const messages = [];
  if (data.inserted.length) {
    messages.push(['ok', `${data.inserted.length} ligne(s) importée(s).`]);
  }
  data.skipped.forEach((ignoree) => {
    const { entry } = lignes[ignoree.ligne - 1];
    messages.push(['ko', `${entry.nom} ${entry.prenom} (${entry.date || 'sans date'}) : ${ignoree.raison}`]);
  });
  showFeedback(messages);

  // Les lignes enregistrées disparaissent, celles qui ont été refusées restent à corriger.
  const importees = new Set(data.inserted.map((ligne) => ligne.ligne));
  lignes.forEach(({ tr }, index) => {
    if (importees.has(index + 1)) tr.remove();
    else tr.classList.add('row-error');
  });
  if (importRows.children.length === 0) addImportRows(3);

  loadPointages();
});

function showFeedback(messages) {
  importFeedback.replaceChildren(...messages.map(([type, texte]) => {
    const p = document.createElement('p');
    p.className = type;
    p.textContent = texte;
    return p;
  }));
}

checkStatus();
