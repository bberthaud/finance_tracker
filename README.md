# Suivi financier

Tableau de bord budgétaire personnel : les opérations bancaires sont extraites avec [Woob](https://woob.tech), catégorisées dans Notion, puis analysées dans une application Streamlit (épargne par période, répartition des dépenses, détail des transactions).

Le fonctionnement détaillé et les schémas de flux sont dans [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Démo en 30 secondes (données fictives)

```bash
make demo
# ou : DATA_SOURCE=demo APP_PASSWORD=demo .venv/bin/python -m streamlit run app.py
```

Ouvrir http://localhost:8501, mot de passe `demo`. Les données viennent de `demo/transactions_demo.csv`, généré par `make demo-data` (reproductible, aucune donnée réelle).

## Installation

Le venv du projet est un environnement Linux (WSL) : anacron et Woob s'exécutent sous Linux (`.venv/bin/python`). Depuis PowerShell, préfixer les commandes par `wsl -e bash -lc "cd /mnt/c/Users/bapti/Documents/Python/finance_tracker && ..."`.

Installer [uv](https://docs.astral.sh/uv/) dans WSL (une fois) :

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Puis, dans le dépôt :

```bash
uv sync --group dev --group sync
make demo
```

`uv sync` installe les dépendances de l'application, le groupe `dev` (pytest, ruff, …) et le groupe `sync` (Woob). `requirements.txt` est un export pour Streamlit Community Cloud, sans ces deux groupes : ne pas l'éditer à la main.

## Configuration

Fichier `.env` (non versionné) :

| Variable | Rôle |
|---|---|
| `APP_PASSWORD` | Mot de passe de l'interface |
| `NOTION_TOKEN` | Token d'intégration Notion |
| `NOTION_DATABASE_ID` | ID de la base Transactions |
| `BANK_PERSO_ID`, `BANK_JOINT_ID` | Identifiants Woob des comptes |
| `DRIVE_FOLDER_ID` | Dossier Google Drive contenant `transactions.csv` |
| `DATA_SOURCE` | `demo` pour utiliser les données fictives |

Identifiants Google dans `.streamlit/secrets.toml` (non versionné) :

```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"
```

## Utilisation

```bash
.venv/bin/python -m streamlit run app.py   # tableau de bord
.venv/bin/python notion.py                 # synchro banque → Notion (lancée par cron via sync_notion.sh)
```

## Tests et qualité

```bash
make test        # lint (ruff) + toute la suite
make test-ui     # tests de l'interface uniquement
make coverage    # rapport HTML dans htmlcov/
```

La suite combine tests unitaires paramétrés, tests de propriétés (Hypothesis) et tests d'interface Streamlit sans navigateur (AppTest). Aucun appel réseau : banque, Notion et Drive sont simulés. La CI GitHub Actions (`.github/workflows/ci.yml`) lance lint et tests à chaque push.
