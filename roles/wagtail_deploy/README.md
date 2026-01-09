# wagtail_deploy

Deploy Wagtail Django sites with uv-managed Python, systemd, and optional Traefik routing.

## Description

This role deploys Wagtail applications (e.g. homepage, python-podcast) using either rsync from a local checkout or a git repository. It provisions the PostgreSQL database/user via `postgres_install`, creates the service user, installs the Python environment via uv, renders a `.env` file, runs migrations/collectstatic/update_index, configures systemd, and optionally writes Traefik dynamic config.

## Requirements

- Ubuntu host with systemd
- `uv` installed on the target host (default: `/usr/local/bin/uv`)
- Ansible collections:
  - `ansible.posix`

## Role Variables

### Required Variables

```yaml
wagtail_service_name: "homepage"
wagtail_deploy_method: rsync  # rsync or git
wagtail_fqdn: "example.com"
wagtail_traefik_host_rule: "Host(`example.com`)"
wagtail_app_port: 10013

# Secrets (no defaults)
wagtail_django_secret_key: "..."
wagtail_postgres_password: "..."
wagtail_django_aws_access_key_id: "..."
wagtail_django_aws_secret_access_key: "..."
wagtail_django_aws_storage_bucket_name: "..."
wagtail_cloudfront_domain: "..."
wagtail_django_sentry_dsn: "..."
wagtail_django_mailgun_api_key: "..."
wagtail_mailgun_sender_domain: "..."
wagtail_django_server_email: "..."
```

### Rsync Deployment

```yaml
wagtail_source_path: "/path/to/wagtail/repo"
wagtail_rsync_excludes_extra:
  - "notebooks"
```

Default rsync excludes include `{{ wagtail_project_slug }}/media`, `backups`, `databases`, and `.venv`.

### Git Deployment

```yaml
wagtail_git_repo: "git@github.com:org/project.git"
wagtail_git_version: "main"
```

### Common Configuration

```yaml
wagtail_global_python: "/opt/python/python"  # or python3.14
wagtail_uv_path: "/usr/local/bin/uv"
wagtail_gunicorn_workers: 4
wagtail_gunicorn_timeout: 600
wagtail_django_settings_module: "config.settings.production"
wagtail_admin_url: "hidden_admin/"
wagtail_env_extra:
  INDIEWEB_ME_URL: "https://example.com/user/"
```

### PostgreSQL Provisioning

```yaml
wagtail_postgres_version: "17"
wagtail_postgres_database: "homepage"
wagtail_postgres_user: "homepage"
wagtail_postgres_password: "{{ service_secrets.postgres_password }}"
wagtail_postgres_repo_enabled: true
```

For a complete list of variables, see `roles/wagtail_deploy/defaults/main.yml`.

## Dependencies

- `local.ops_library.postgres_install`

## Example Playbook

### Rsync deployment

```yaml
- name: Deploy Wagtail (rsync)
  hosts: wagtail_hosts
  become: true
  vars:
    wagtail_service_name: homepage
    wagtail_deploy_method: rsync
    wagtail_source_path: "/Users/jochen/projects/homepage"
    wagtail_fqdn: "example.com"
    wagtail_traefik_host_rule: "Host(`example.com`) || Host(`www.example.com`)"
    wagtail_app_port: 10013
    wagtail_global_python: "/opt/python/python"
    wagtail_django_secret_key: "{{ service_secrets.django_secret_key }}"
    wagtail_postgres_password: "{{ service_secrets.postgres_password }}"
    wagtail_django_aws_access_key_id: "{{ service_secrets.django_aws_access_key_id }}"
    wagtail_django_aws_secret_access_key: "{{ service_secrets.django_aws_secret_access_key }}"
    wagtail_django_aws_storage_bucket_name: "{{ service_secrets.django_aws_storage_bucket_name }}"
    wagtail_cloudfront_domain: "{{ service_secrets.cloudfront_domain }}"
    wagtail_django_sentry_dsn: "{{ service_secrets.django_sentry_dsn }}"
    wagtail_django_mailgun_api_key: "{{ service_secrets.django_mailgun_api_key }}"
    wagtail_mailgun_sender_domain: "{{ service_secrets.mailgun_sender_domain }}"
    wagtail_django_server_email: "{{ service_secrets.django_server_email }}"
  roles:
    - role: local.ops_library.wagtail_deploy
```

### Git deployment

```yaml
- name: Deploy Wagtail (git)
  hosts: wagtail_hosts
  become: true
  vars:
    wagtail_service_name: python-podcast
    wagtail_deploy_method: git
    wagtail_git_repo: "git@github.com:org/python-podcast.git"
    wagtail_git_version: "main"
    wagtail_fqdn: "python-podcast.de"
    wagtail_traefik_host_rule: "Host(`python-podcast.de`) || Host(`www.python-podcast.de`)"
    wagtail_app_port: 10014
    wagtail_django_secret_key: "{{ service_secrets.django_secret_key }}"
    wagtail_postgres_password: "{{ service_secrets.postgres_password }}"
    wagtail_django_aws_access_key_id: "{{ service_secrets.django_aws_access_key_id }}"
    wagtail_django_aws_secret_access_key: "{{ service_secrets.django_aws_secret_access_key }}"
    wagtail_django_aws_storage_bucket_name: "{{ service_secrets.django_aws_storage_bucket_name }}"
    wagtail_cloudfront_domain: "{{ service_secrets.cloudfront_domain }}"
    wagtail_django_sentry_dsn: "{{ service_secrets.django_sentry_dsn }}"
    wagtail_django_mailgun_api_key: "{{ service_secrets.django_mailgun_api_key }}"
    wagtail_mailgun_sender_domain: "{{ service_secrets.mailgun_sender_domain }}"
    wagtail_django_server_email: "{{ service_secrets.django_server_email }}"
  roles:
    - role: local.ops_library.wagtail_deploy
```

## Handlers

- `reload systemd`
- `restart wagtail`

## Testing

```bash
cd /path/to/ops-library
just test-role wagtail_deploy
```

## License

MIT
