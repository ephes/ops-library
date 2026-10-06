# opaq_app_deploy

Deploy the Opaq app — daybook's `services/opaq_app`, the company cash page —
on a Debian host: a Django app (SQLite, WhiteNoise, gunicorn on loopback)
behind a Traefik `ipAllowList` **and** the app's own password login. Design:
daybook `docs/specs/2026-10-06-opaq-app.md`.

## What it does

- Creates the system user `opaq-app` with a `0700` home.
- Rsyncs `src/` and `services/opaq_app/` plus `pyproject.toml` and `uv.lock`
  from a daybook checkout into `site/` (`--delete` inside those trees only).
  The database lives in `data/`, outside the synced tree, so a sync can never
  remove it.
- Installs only the locked `opaq-app` dependency group (Django, gunicorn,
  WhiteNoise) with `uv sync --frozen --only-group opaq-app --no-install-project`.
  daybook's own modules come from the synced `src/` via `PYTHONPATH`, so none
  of daybook's desktop dependencies reach the server.
- Renders `opaq-app.env` (`0600`), runs `migrate` and `collectstatic`, and
  restricts the database to `0600`.
- Runs gunicorn under systemd with `ProtectSystem=strict` (only `data/`
  writable), no capabilities, `UMask=0077`.
- Publishes `/etc/traefik/dynamic/opaq-app.yml`: the allowlist guards the HTTPS
  and the HTTP router; TLS uses the file-provider certificate (`tls: {}`).
- Checks `/healthz` on loopback.

It creates **no user accounts** and stores no password: the owner runs
`manage.py createsuperuser` over SSH (see ops-control `docs/DAYBOOK_OPAQ.md`).
The upload token never reaches the host; only its SHA-256 digest does.

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `opaq_app_source_path` | `""` | Absolute path to the daybook checkout (required). |
| `opaq_app_secret_key` | `""` | Django secret key, 50+ of `[A-Za-z0-9_-]` (required). |
| `opaq_app_upload_token_sha256` | `""` | SHA-256 hex digest of the upload token (required). |
| `opaq_app_traefik_host` | `""` | Host name of the route (required with Traefik). |
| `opaq_app_allowed_networks` | `[]` | CIDR ranges admitted by Traefik; validated with `is_cidr`; must not be empty with Traefik. |
| `opaq_app_app_port` | `10065` | Loopback port. |
| `opaq_app_traefik_config_path` | `/etc/traefik/dynamic/opaq-app.yml` | Route file. |
| `opaq_app_python_version` | `3.14` | uv-managed Python. |

Paths (`opaq_app_home`, `opaq_app_site_path`, `opaq_app_data_path`,
`opaq_app_database_path`, `opaq_app_static_root`, `opaq_app_env_file`,
`opaq_app_venv_path`) are in `defaults/main.yml`.
