# Paperless Deploy Role

Deploy [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) using uv-managed Python, Redis, PostgreSQL, scanner SFTP integration, and Traefik routing.

## Capabilities

- Creates the `paperless` system user, directory layout, and storage symlinks
- Installs prerequisite packages plus Redis/PostgreSQL via `redis_install`/`postgres_install`
- Manages uv virtualenvs, release artifacts, and NLTK dataset downloads
- Renders `.env`, gunicorn config, systemd units, Traefik dynamic config, and scanner SSH drop-ins
- Performs health checks (`systemctl` + HTTP `/api/`) before finishing

## Usage

```yaml
- hosts: paperless
  roles:
    - role: local.ops_library.paperless_deploy
      vars:
        paperless_secret_key: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['paperless_secret_key'] }}"
        paperless_admin_password: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['paperless_admin_password'] }}"
        paperless_postgres_password: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['postgres_password'] }}"
```

Refer to `roles/paperless_deploy/README.md` for the full variable table, scanner options, and troubleshooting guidance.
