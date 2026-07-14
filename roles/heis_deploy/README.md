# heis_deploy

Deploy the Heis Django site with uv, systemd, and Traefik while preserving the
SQLite database and uploaded media across source deployments.

## Description

This role mirrors the legacy `heis/deploy/` flow: rsync source code, create a uv-managed venv, render a `.env`, run `migrate` and `collectstatic`, write a gunicorn launcher + systemd unit, and configure Traefik routing.

## Requirements

- Debian or Ubuntu host with systemd
- `uv` installed on the target host (role uses `local.ops_library.uv_install` by default; path: `/usr/local/bin/uv`)
- Ansible collections:
  - `ansible.posix`

The role installs its small host-side runtime prerequisites (`fish`, `rsync`,
and `sqlite3`) by default. Override `heis_prerequisite_packages` when the host
uses different package names.

## Required Variables

```yaml
heis_source_path: "/path/to/heis"
heis_fqdn: "heis-adler.de"
heis_traefik_host_rule: "Host(`heis-adler.de`) || Host(`www.heis-adler.de`)"
# Optional: restrict TLS/ACME names while retaining a broader HTTP router.
heis_traefik_tls_host_rule: "{{ heis_traefik_host_rule }}"
heis_django_secret_key: "..."
```

## Optional Variables

```yaml
heis_user: "heis"
heis_group: "heis"
heis_home: "/home/heis"

heis_site_path: "{{ heis_home }}/site"
heis_app_port: 10019
heis_python_version: "python3.13"
heis_gunicorn_workers: 4
heis_gunicorn_timeout: 3600
heis_prerequisite_packages:
  - fish
  - rsync
  - sqlite3

heis_django_settings_module: "config.settings.production"
heis_django_admin_url: "heis_admin/"
heis_django_allowed_hosts: "{{ heis_fqdn }},localhost"
heis_serve_media: false
heis_setup_default_pages: true
heis_seed_content: true

heis_traefik_enabled: true
heis_traefik_canonical_redirect_regex: ""
heis_traefik_canonical_redirect_replacement: ""
```

For the full list, see `defaults/main.yml`.

## Persistent Data

Source rsync deliberately excludes SQLite database files, SQLite WAL/SHM
sidecars, `media/`, and backup directories. Production content must be moved
with a separate backup/restore or promotion workflow; a normal code deployment
never imports a controller-local database or uploaded media tree.

Set `heis_setup_default_pages: false` and `heis_seed_content: false` for a
production database whose approved CMS content must only be changed through
Wagtail or an explicit promotion workflow.

## Dependencies

- `local.ops_library.uv_install`

## Example Playbook

```yaml
- name: Deploy Heis
  hosts: heis
  become: true
  vars:
    heis_source_path: "/Users/jochen/projects/heis"
    heis_fqdn: "heis-adler.de"
    heis_traefik_host_rule: "Host(`heis-adler.de`) || Host(`www.heis-adler.de`)"
    heis_traefik_tls_host_rule: "{{ heis_traefik_host_rule }}"
    heis_django_secret_key: "{{ service_secrets.django_secret_key }}"
  roles:
    - role: local.ops_library.uv_install
    - role: local.ops_library.heis_deploy
```

## License

MIT
