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
- one Wyoming STT sidecar process on port `10300`
- `whisper.cpp` as the default STT backend on `studio`, with `mlx-whisper` as fallback
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
voxhelm_stt_backend: "whispercpp"
voxhelm_stt_fallback_backend: "mlx"
voxhelm_mlx_model: "mlx-community/whisper-large-v3-mlx"
voxhelm_whispercpp_model: "ggml-large-v3.bin"
voxhelm_whispercpp_bin: "/opt/homebrew/bin/whisper-cli"
voxhelm_whispercpp_processors: 4
voxhelm_model_cache_dir: "/opt/apps/voxhelm/site/var/models"
voxhelm_wyoming_stt_enabled: true
voxhelm_wyoming_stt_host: "0.0.0.0"
voxhelm_wyoming_stt_port: 10300
voxhelm_wyoming_stt_backend: ""
voxhelm_wyoming_stt_model: ""
voxhelm_wyoming_stt_language: ""
voxhelm_wyoming_stt_languages:
  - "de"
  - "en"
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

## Wyoming STT Notes

- The Wyoming listener is STT-only in this slice. TTS/Piper is not deployed here.
- `voxhelm_wyoming_stt_backend` and `voxhelm_wyoming_stt_model` are optional. If
  unset, the sidecar reuses the service-wide STT defaults.
- There is no cross-process lane scheduler yet. The Wyoming sidecar has its own
  process and its own in-process serialization, but it can still contend with
  the HTTP API and batch worker for CPU, RAM, and model cache use on `studio`.
- The role verifies the sidecar by checking the launchd unit state and waiting
  for the configured TCP port to listen locally on the target host.

## License

MIT
