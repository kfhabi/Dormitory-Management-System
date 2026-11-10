# Dormitory Management System

## Project structure

```text
dms/
  apps/
    accounts/             Account model, authentication, sessions and admin commands
      management/commands/
      migrations/
    core/                 Shared forms, navigation, error/health views and template filters
      templatetags/
    dormitory/            Dormitory models, business services and page views
      migrations/
  config/                 Django settings, URL routes, WSGI and ASGI entry points
  deploy/                 Database initialization and container startup
  static/
    css/                  Application styles
    js/                   Application scripts
  templates/
    accounts/             Login and password pages
    dormitory/            Business pages and shared page components
    base.html             Shared page layout
```

The three local apps registered in `config/settings.py` are `accounts`, `core`
and `dormitory`. Rooms, applications, contracts, invoices, maintenance,
transfers, notifications and reports are implemented together in `dormitory`;
they do not need separate empty apps or template directories. The current
business operations share models and transactions, so keep this arrangement
unless there is a concrete maintenance reason to split it. If individual
modules become difficult to maintain, they can be divided into smaller
modules within the same app first.

Keep `migrations`, `management/commands`, `templatetags` and the Python
`__init__.py` files: these contain database history or modules used by Django.
The local `.venv` is used by `start.ps1`, `.vscode` stores optional editor
settings, and `.git` stores version history. Python may create `__pycache__`
directories automatically; they are ignored by Git.

## Deployment on Render

See [the Render deployment guide](deploy/RENDER.md) for a free demo using a
Render web service and an external MySQL database, preserving existing business
data and accounts. The guide covers the provider's expiry limit, TLS CA setup,
data transfer, GitHub and environment configuration. The web image uses the root
`Dockerfile`.

## Production deployment with Docker Compose

The production stack runs Django behind Gunicorn and MySQL 8.4. The web
container listens on host loopback port `8000`; terminate HTTPS with a reverse
proxy on the host and forward the original `Host` and `X-Forwarded-Proto`
headers. The reverse proxy should be the only public entry point.

### 1. Prepare secrets and domain settings

From the repository root in PowerShell:

```powershell
Copy-Item deploy\production.env.example deploy\production.env
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Edit `deploy\production.env` locally. Set `SECRET_KEY`, `DB_PASSWORD`, and
`MYSQL_ROOT_PASSWORD` to different, unique random values, and replace the
example domain in `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`. Do not commit this
file. The repository ignores it.

The sample enables HTTPS redirects and secure cookies for a host-based TLS
proxy. Keep `TRUST_PROXY=True` only when the app is reachable exclusively
through a trusted proxy that overwrites `X-Forwarded-Proto`. Leave HSTS at `0`
until HTTPS is verified. Enable `SECURE_HSTS_INCLUDE_SUBDOMAINS` and
`SECURE_HSTS_PRELOAD` only if every affected subdomain is HTTPS-ready and you
intend to opt into browser preload lists.

### 2. Create the production schema

For a new MySQL data volume, Compose runs `deploy/01_schema.sql` automatically
on the first database initialization. The Django entrypoint then runs Django
migrations and collects static assets before starting Gunicorn.

The schema script is **not** re-run when a populated volume already exists.
Back up existing data and apply any required schema changes deliberately
before deploying to an existing database; do not delete the volume to force
initialization.

### 3. Build and start

```powershell
docker compose --env-file deploy\production.env config --quiet
docker compose --env-file deploy\production.env up --build -d
docker compose --env-file deploy\production.env ps
docker compose --env-file deploy\production.env logs --tail 100 web
```

The web health check calls `/api/v1/health`, which returns `503` if MySQL is not
available. Check that the reverse proxy serves the configured HTTPS domain
before enabling HSTS.

### 4. Bootstrap the first administrator

Create the initial admin account interactively after the stack is healthy:

```powershell
docker compose --env-file deploy\production.env exec web python manage.py bootstrap_admin --email admin@dms.example.com
```

The command prompts for a password and does not overwrite a usable password.
Do not enable demo setup in production.

### Operations

```powershell
docker compose --env-file deploy\production.env logs -f web
docker compose --env-file deploy\production.env exec web python manage.py check --deploy
docker compose --env-file deploy\production.env down
```

`docker compose down` preserves the named MySQL volume. Do not use
`docker compose down -v` on production data.

## Local development

Use the root `.env.example` as the template for a local `.env`, install the
Python requirements into a virtual environment, prepare a local MySQL database
with `deploy/01_schema.sql`, then run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.ps1
```

`start.ps1` runs Django checks and migrations before starting the development
server. It may create demo credentials only when `DEBUG=True`; keep generated
credentials private and change demo passwords after first login.
