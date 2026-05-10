# Budget Familial — App Web (Flask)

## Fichiers principaux
- `app.py` → routes Flask, logique métier, emails transactionnels
- `db.py` → couche base de données (SQLite local / PostgreSQL sur Render)
- `templates/` → templates Jinja2
- `static/style.css` → CSS global
- `static/app.js` → JS global (sidebar, navigation période)

## Stack
- Python + Flask + Flask-Login
- SQLite en local, PostgreSQL en production (Render)
- Emails transactionnels via Brevo API
- Déploiement : Render (Web Service)

## Variables d'environnement requises (Render)
- `SECRET_KEY` — clé secrète Flask
- `DATABASE_URL` — URL PostgreSQL
- `BREVO_API_KEY` — clé API Brevo pour les emails
- `MAIL_FROM` — adresse expéditeur vérifiée dans Brevo

## Règle permanente
À chaque nouvelle fonctionnalité ou modification de l'app, mettre à jour le guide d'utilisation dans `templates/guide.html`.

## Fonctionnalités actuelles
- Inscription / connexion / mot de passe oublié
- Gestion des membres du foyer (Parents et Enfants)
- Transactions (dépenses et revenus) par mois/catégorie
- Dashboard avec résumé mensuel et budgets par catégorie
- Statistiques (graphiques par catégorie, par payeur)
- Paramètres : salaires mensuels, plafonds budgétaires, charges fixes, devise, profil du foyer
- Gestion des devises (12 devises disponibles, stockée par foyer)
- Email de bienvenue automatique à l'inscription (Brevo)
- Page de contact publique (accessible sans connexion)
- Export PDF
- Interface d'administration (/admin) : gestion des comptes, messages de contact, envoi d'emails groupés
- Guide d'utilisation (/guide)
