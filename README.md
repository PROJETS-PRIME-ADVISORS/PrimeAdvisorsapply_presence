# Pointage de présence — PRIME ADVISORS SB, Inc.

Les employés scannent un QR code affiché à l'entrée, saisissent leur nom et leur
prénom : le premier passage de la journée enregistre l'arrivée, le suivant le
départ. La page `/admin`, protégée par un mot de passe, affiche les pointages,
les exporte en CSV et permet de reporter le registre papier.

Application Flask (Python), base SQLite en local et Postgres en production.

---

## 1. Structure

```
pointage-app/            ← dossier racine du projet sur Vercel
├── app.py               application Flask : routes et base de données
├── templates/           pages HTML (index.html = pointage, admin.html = administration)
├── public/static/       CSS, JavaScript et logo, servis par le CDN de Vercel
├── tests/               tests automatiques
├── requirements.txt     dépendances de l'application
├── requirements-dev.txt dépendances supplémentaires pour les tests
├── .env.example         modèle de configuration à copier en .env
├── .python-version      version de Python utilisée par Vercel
└── .vercelignore        fichiers qui ne doivent jamais partir en ligne
```

## 2. Travailler en local

Prérequis : [Python](https://www.python.org/downloads/) 3.12 ou plus récent.

```bash
cd pointage-app
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

Sur macOS ou Linux, la deuxième ligne devient `source .venv/bin/activate`.

Copier ensuite `.env.example` en `.env` et renseigner au moins `ADMIN_PASSWORD`
et `SESSION_SECRET` (le fichier `.env` n'est jamais versionné) :

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Puis lancer le serveur :

```bash
python app.py
```

Le site répond sur `http://localhost:5000`, l'administration sur
`http://localhost:5000/admin`. Sans `DATABASE_URL`, les pointages sont
enregistrés dans le fichier `pointage.db`, à côté de `app.py`.

Pour essayer depuis un téléphone du bureau, ouvrir
`http://<adresse IP du PC>:5000` (les deux appareils sur le même réseau).

### Tests

```bash
python -m pytest
```

Les tests couvrent l'arrivée, le départ, le double scan, le rapprochement des
noms, l'accès administrateur, l'import et l'export. Ils utilisent une base
temporaire : ni `pointage.db` ni la base de production ne sont touchés.

## 3. Configuration

| Variable | Rôle |
|---|---|
| `ADMIN_PASSWORD` | Mot de passe de `/admin`. **Obligatoire.** 12 caractères minimum en production. |
| `SESSION_SECRET` | Signature du cookie de session. **Obligatoire.** 32 caractères minimum en production. |
| `DATABASE_URL` | Base Postgres de production. Vide en local : SQLite est alors utilisé. |
| `DELAI_MIN_DEPART_MINUTES` | Délai minimal entre l'arrivée et le départ (30 par défaut). |
| `PORT` | Port du serveur local (5000 par défaut). |

L'application refuse de démarrer si `ADMIN_PASSWORD` ou `SESSION_SECRET`
manquent : une erreur visible vaut mieux qu'un mot de passe par défaut.

## 4. Mise en ligne sur Vercel

**a. La base de données d'abord.** Le disque des fonctions Vercel n'est pas
conservé d'un appel à l'autre : un fichier SQLite y perdrait les pointages.
Dans le tableau de bord Vercel : **Storage → Create Database → Neon** (ou un
autre fournisseur Postgres du Marketplace), puis connecter la base au projet.
Vercel injecte alors `DATABASE_URL` automatiquement. Les tables sont créées
toutes seules au premier appel.

**b. Importer le dépôt.** *Add New → Project*, choisir ce dépôt GitHub, puis —
c'est le point à ne pas manquer — régler **Root Directory** sur `pointage-app`.
Vercel détecte Flask et n'a besoin d'aucun autre réglage.

**c. Variables d'environnement.** Ajouter `ADMIN_PASSWORD` et `SESSION_SECRET`
(*Settings → Environment Variables*), pour *Production* et *Preview*.

**d. Déployer**, puis vérifier la page d'accueil, un pointage, la connexion à
`/admin` et l'export CSV.

**e. Le QR code** doit pointer vers l'adresse de production
(`https://<projet>.vercel.app/`), à générer une fois le domaine définitif connu.

Ensuite, chaque `push` sur `main` met la production à jour ; les autres branches
reçoivent une adresse de test. Attention : si `DATABASE_URL` est aussi active en
*Preview*, les déploiements de test écrivent dans la base de production. Neon
sait créer une base séparée par branche, à activer dans l'intégration.

## 5. Sécurité

- `.env`, `pointage.db` et les `__pycache__` ne doivent jamais être versionnés
  (`.gitignore` s'en charge). Un fichier poussé sur GitHub reste lisible dans
  l'historique même après suppression.
- **Le mot de passe d'administration et la clé de session présents dans les
  premiers commits sont publics : ils doivent être remplacés par de nouvelles
  valeurs, jamais réutilisés.**
- Protections en place : dix tentatives de connexion par quart d'heure et par
  adresse IP, cookie de session `HttpOnly`/`SameSite` (et `Secure` en ligne),
  noms limités aux lettres, export CSV protégé contre les formules Excel.
- Limite connue et assumée : la page de pointage est publique. Qui connaît
  l'adresse peut pointer au nom de quelqu'un d'autre. Le QR code affiché dans
  les locaux reste la seule barrière.

## 6. Règles de fonctionnement

- L'heure enregistrée est celle du serveur, fuseau `Africa/Abidjan`.
- Premier passage : arrivée. Passage suivant : départ, mais pas avant
  `DELAI_MIN_DEPART_MINUTES` (30 minutes) — sans quoi un double scan du matin
  clôturerait la journée à 08 h 01.
- Les noms sont enregistrés en majuscules et les prénoms avec une capitale
  initiale. Le rapprochement du matin et du soir ignore la casse, les accents,
  les espaces et la ponctuation : « Éclésiaste » et « ECLESIASTE » sont la même
  personne.
- Un pointage commencé après minuit compte pour le jour suivant.
- Aucun pointage n'est modifiable ni supprimable depuis l'application : c'est
  volontaire. Une correction se fait directement en base.

## 7. Travailler à deux

```bash
git pull                          # récupérer le travail de l'autre
git checkout -b ma-modification   # une branche par sujet
python -m pytest                  # avant de pousser
git push -u origin ma-modification
```

Ouvrir ensuite une *pull request* sur GitHub : elle reçoit une adresse de test
Vercel, ce qui permet de relire et d'essayer la modification avant qu'elle
n'arrive en production.
