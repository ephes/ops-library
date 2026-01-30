# marina_deploy

Deploy the Marina Django site with uv, systemd, and Traefik.

## Description

This role mirrors the legacy `marina/deploy/` flow: rsync source code, create a uv-managed venv, render a `.env`, run `migrate` and `collectstatic`, write a gunicorn launcher + systemd unit, and configure Traefik routing.

## Requirements

- Ubuntu host with systemd
- `uv` installed on the target host (role uses `local.ops_library.uv_install` by default; path: `/usr/local/bin/uv`)
- Ansible collections:
  - `ansible.posix`

## Required Variables

```yaml
marina_source_path: "/path/to/marina"
marina_fqdn: "marina-adler.de"
marina_traefik_host_rule: "Host(`marina-adler.de`) || Host(`www.marina-adler.de`)"
marina_django_secret_key: "..."
```

## Optional Variables

```yaml
marina_user: "marina"
marina_group: "marina"
marina_home: "/home/marina"

marina_site_path: "{{ marina_home }}/site"
marina_app_port: 10019
marina_python_version: "python3.13"
marina_gunicorn_workers: 4
marina_gunicorn_timeout: 3600

marina_django_settings_module: "config.settings.production"
marina_django_admin_url: "hidden_admin/"
marina_django_allowed_hosts: "{{ marina_fqdn }},localhost"

marina_traefik_enabled: true
```

For the full list, see `defaults/main.yml`.

## Dependencies

- `local.ops_library.uv_install`

## Example Playbook

```yaml
- name: Deploy Marina
  hosts: marina
  become: true
  vars:
    marina_source_path: "/Users/jochen/projects/marina"
    marina_fqdn: "marina-adler.de"
    marina_traefik_host_rule: "Host(`marina-adler.de`) || Host(`www.marina-adler.de`)"
    marina_django_secret_key: "{{ service_secrets.django_secret_key }}"
  roles:
    - role: local.ops_library.uv_install
    - role: local.ops_library.marina_deploy
```

## License

MIT
