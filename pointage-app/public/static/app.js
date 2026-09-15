const TIMEZONE = 'Africa/Abidjan';
const STORAGE_KEY = 'pointage-identite';

const clockEl = document.getElementById('clock');

function tick() {
  // Heure d'Abidjan, celle qu'enregistre le serveur, quel que soit le fuseau du téléphone.
  clockEl.textContent = new Date().toLocaleString('fr-FR', {
    timeZone: TIMEZONE, weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}
tick();
setInterval(tick, 1000);

const form = document.getElementById('pointage-form');
const nomInput = document.getElementById('nom');
const prenomInput = document.getElementById('prenom');
const memoriserInput = document.getElementById('memoriser');
const result = document.getElementById('result');
const submitBtn = form.querySelector('button[type="submit"]');

restoreIdentity();

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const nom = nomInput.value.trim();
  const prenom = prenomInput.value.trim();

  submitBtn.disabled = true;
  submitBtn.textContent = 'Enregistrement...';

  try {
    const response = await fetch('/api/pointage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nom, prenom }),
    });
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      showResult('error', data.error || 'Une erreur est survenue. Réessayez dans un instant.');
      return;
    }

    rememberIdentity(data.nom, data.prenom);
    if (data.type === 'arrivee') {
      showResult('success', `Bonjour ${data.prenom}, arrivée enregistrée à ${hhmm(data.heure)}.`);
    } else if (data.type === 'depart') {
      showResult('success', `Au revoir ${data.prenom}, départ enregistré à ${hhmm(data.heure)}.`);
    } else if (data.type === 'deja_arrive') {
      showResult('info', `${data.prenom}, votre arrivée est déjà enregistrée (${hhmm(data.heure_arrivee)}). Le départ pourra être pointé à partir de ${data.depart_possible}.`);
    } else {
      showResult('info', `${data.prenom}, la journée est déjà complète (arrivée ${hhmm(data.heure_arrivee)}, départ ${hhmm(data.heure_depart)}).`);
    }
  } catch (error) {
    showResult('error', 'Impossible de contacter le serveur. Vérifiez la connexion.');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Pointer';
  }
});

function hhmm(heure) {
  return heure ? heure.slice(0, 5) : '—';
}

function showResult(type, message) {
  result.textContent = message;
  result.className = `result ${type}`;
}

// Le nom tapé le matin est repris le soir à l'identique : le départ retrouve toujours l'arrivée.
function rememberIdentity(nom, prenom) {
  if (memoriserInput.checked) {
    nomInput.value = nom;
    prenomInput.value = prenom;
  } else {
    nomInput.value = '';
    prenomInput.value = '';
  }
  try {
    if (memoriserInput.checked) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ nom, prenom }));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch (error) {
    // Stockage indisponible (navigation privée) : le pointage fonctionne sans.
  }
}

function restoreIdentity() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    if (saved) {
      nomInput.value = saved.nom || '';
      prenomInput.value = saved.prenom || '';
    }
  } catch (error) {
    // Rien de mémorisé ou stockage indisponible.
  }
}
