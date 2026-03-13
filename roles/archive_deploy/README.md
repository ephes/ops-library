# archive_deploy

Deploy the Archive Django service on a host with a local SQLite database, systemd, and Traefik.

This role covers the deployed Archive MVP through Milestone 2:

- source deployment via `rsync` or `git`
- `uv`-managed virtualenv
- Django migrations and static collection
- admin/editor bootstrap user
- systemd service
- public Traefik ingress
- automatic service restart when app source, environment, or dependency state changes

Backup and restore are intentionally handled through Echoport orchestration, not `archive_backup` /
`archive_restore` roles. The primary backup target is the SQLite database at
`{{ archive_db_path }}` via the existing `echoport-backup` FastDeploy service.

## Contributor Notes

The deploy helper extraction keeps the public role entrypoint unchanged while
moving the duplicated single-unit systemd and Traefik rendering steps into the
internal helper role `local.ops_library.webapp_deploy_internal`. Archive still
owns its validation, source deployment, Django setup, templates, handlers, and
health verification flow.

## Variables

Required:

```yaml
archive_django_secret_key: "long-random-secret"
archive_api_token: "long-random-api-token"
archive_admin_username: "archive"
archive_admin_password: "long-random-password"
archive_traefik_host: "archive.home.xn--wersdrfer-47a.de"
```

Common overrides:

```yaml
archive_source_path: "/Users/jochen/projects/archive"
archive_deploy_method: rsync
archive_django_allowed_hosts:
  - "127.0.0.1"
  - "archive.home.xn--wersdrfer-47a.de"
archive_django_csrf_trusted_origins:
  - "https://archive.home.xn--wersdrfer-47a.de"
```

## Example

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.archive_deploy
      vars:
        archive_source_path: "/Users/jochen/projects/archive"
        archive_django_secret_key: "{{ archive_secrets.django_secret_key }}"
        archive_api_token: "{{ archive_secrets.api_token }}"
        archive_admin_username: "{{ archive_secrets.admin_username }}"
        archive_admin_password: "{{ archive_secrets.admin_password }}"
        archive_traefik_host: "archive.home.xn--wersdrfer-47a.de"
        archive_django_allowed_hosts:
          - "127.0.0.1"
          - "archive.home.xn--wersdrfer-47a.de"
        archive_django_csrf_trusted_origins:
          - "https://archive.home.xn--wersdrfer-47a.de"
```
