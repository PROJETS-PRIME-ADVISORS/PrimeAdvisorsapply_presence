const clockEl = document.getElementById('clock');

function tick() {
  const now = new Date();
  clockEl.textContent = now.toLocaleString('fr-FR', {
    weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}
tick();
setInterval(tick, 1000);

const form = document.getElementById('pointage-form');
const result = document.getElementById('result');
const submitBtn = form.querySelector('button');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const nom = document.getElementById('nom').value.trim();
  const prenom = document.getElementById('prenom').value.trim();

  submitBtn.disabled = true;
  submitBtn.textContent = 'Enregistrement...';

  try {
    const response = await fetch('/api/pointage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nom, prenom }),
    });
    const data = await response.json();

    if (!response.ok) {
      showResult('error', data.error || "Une erreur est survenue.");
    } else if (data.type === 'arrivee') {
      showResult('success', `Bonjour ${data.prenom}, arrivée enregistrée à ${data.heure}.`);
    } else if (data.type === 'depart') {
      showResult('success', `Bonne soirée ${data.prenom}, départ enregistré à ${data.heure}.`);
    } else {
      showResult('info', `${data.prenom}, la journée est déjà complète (arrivée ${data.heure_arrivee}, départ ${data.heure_depart}).`);
    }
    form.reset();
  } catch (error) {
    showResult('error', "Impossible de contacter le serveur. Vérifiez la connexion.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Pointer';
  }
});

function showResult(type, message) {
  result.textContent = message;
  result.className = `result ${type}`;
}
