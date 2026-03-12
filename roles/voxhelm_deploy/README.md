# voxhelm_deploy

Deploy Voxhelm on macOS using `uv`, `uvicorn`, and a launchd `LaunchDaemon`.

## Description

This role deploys the Voxhelm service to the `studio` Mac Studio. It syncs the
local source tree, installs dependencies with `uv sync --frozen --no-dev`,
renders a shell environment file, applies Django migrations, creates launcher
scripts for the HTTP API and the Django Tasks worker, installs launchd plists,
and verifies both the HTTP health endpoint and worker launchd state locally on
the target host.

Current default runtime:

- one `uvicorn` HTTP API process
- one Django Tasks `db_worker` process
- bearer-token authentication via environment variables
- filesystem artifact storage by default, with S3/MinIO-compatible env vars available
- no Traefik dependency; the service binds directly on the configured port

## Requirements

- macOS target host
- `uv` installed on the target host
- Ansible collection:
  - `ansible.posix`

## Required Variables

```yaml
voxhelm_source_path: "/Users/jochen/projects/voxhelm"
voxhelm_django_secret_key: "replace-me"
voxhelm_bearer_tokens_env: "archive=replace-me"
```

## Optional Variables

```yaml
voxhelm_app_port: 8787
voxhelm_bind_host: "0.0.0.0"
voxhelm_mlx_model: "mlx-community/whisper-large-v3-turbo"
voxhelm_allowed_hosts:
  - "studio.tailde2ec.ts.net"
  - "studio"
  - "localhost"
  - "127.0.0.1"
voxhelm_allowed_url_hosts: []
voxhelm_trusted_http_hosts: []
voxhelm_uvicorn_log_level: "info"
```

For the full list, see `defaults/main.yml`.

## Example Playbook

```yaml
- name: Deploy Voxhelm
  hosts: macstudio
  gather_facts: true
  roles:
    - role: local.ops_library.uv_install
    - role: local.ops_library.voxhelm_deploy
      vars:
        voxhelm_source_path: "/Users/jochen/projects/voxhelm"
        voxhelm_django_secret_key: "{{ service_secrets.django_secret_key }}"
        voxhelm_bearer_tokens_env: "archive={{ service_secrets.api_token_archive }}"
```

## License

MIT
