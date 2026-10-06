# Work App Deploy Role

Deploys the work app (private `work-ledger` repository: Django + SQLite, an
owner UI and a bearer-token API for coordinating agents) the same way
`homelab_deploy` deploys Homelab.

## What it does

- Creates the `work` system user and `/home/work/site`
- Rsyncs `src/` and `ledger/` (the YAML ledger read by `import_ledger`) from a
  local checkout, and copies `manage.py`, `pyproject.toml` and `uv.lock`.
  `.env`, the SQLite database and `staticfiles/` live in the site directory
  and are never part of a synced tree
- Creates the virtualenv with uv and runs `uv sync --frozen --no-dev --no-install-project`
- Renders `/home/work/site/.env` (mode `0600`) from the variables below,
  runs `migrate` and `collectstatic` (WhiteNoise serves static files)
- Installs the `work-app` systemd unit (gunicorn `src.config.wsgi:application`
  on `127.0.0.1:10011`) through `webapp_deploy_internal`
- Renders the Traefik dual router config (LAN/Tailscale router without auth at
  priority 120, public router with the shared basic auth at priority 100)
  through `webapp_deploy_internal`
- Waits until `http://127.0.0.1:10011/accounts/login/` answers 200

It does not create Django users or API tokens and does not import the YAML
ledger; those are one-time operator steps (see the ops-control runbook).

## Required variables

```yaml
work_app_source_path: ""        # local work-ledger checkout
work_app_secret_key: ""         # >= 50 chars from [A-Za-z0-9_-]
work_app_basic_auth_password: "" # shared Traefik basic auth (when enabled)
```

## Common variables

```yaml
work_app_traefik_host: "work.home.example.com"
work_app_django_allowed_hosts: ["127.0.0.1"]
work_app_django_csrf_trusted_origins: []
work_app_app_port: 10011
work_app_workers: 2
work_app_python_version: "3.14"
work_app_basic_auth_user: "admin"
work_app_internal_ip_ranges: [...]   # same ranges as homelab
```

See `roles/work_app_shared/defaults/main.yml` and `defaults/main.yml` for the full list.

## API clients and basic auth

The public router uses `Authorization` for basic auth and strips it, so the
bearer-token API is reachable only through the internal (LAN/Tailscale)
router. Coordinators run on the Studio inside the Tailnet.

## Example

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.uv_install
    - role: local.ops_library.work_app_deploy
      vars:
        work_app_source_path: "{{ lookup('env', 'PROJECTS_ROOT') }}/work-ledger"
        work_app_secret_key: "{{ work_app_secrets.django_secret_key }}"
        work_app_traefik_host: "work.home.example.com"
        work_app_django_allowed_hosts: ["127.0.0.1", "localhost", "work.home.example.com"]
        work_app_django_csrf_trusted_origins: ["https://work.home.example.com"]
        work_app_basic_auth_password: "{{ traefik_secrets.basic_auth_password }}"
```

## License

MIT
