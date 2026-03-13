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
- one Wyoming STT/TTS sidecar process on port `10300`
- `whisper.cpp` as the default STT backend on `studio`, with `mlx-whisper` as fallback
- `mlx-whisper` as the default Wyoming STT backend for short interactive speech
- `piper` as the default TTS backend on `studio`
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
voxhelm_tts_backend: "piper"
voxhelm_tts_max_input_chars: 5000
voxhelm_mlx_model: "mlx-community/whisper-large-v3-mlx"
voxhelm_whispercpp_model: "ggml-large-v3.bin"
voxhelm_whispercpp_bin: "/opt/homebrew/bin/whisper-cli"
voxhelm_whispercpp_processors: 4
voxhelm_stt_debug_logging: false
voxhelm_model_cache_dir: "/opt/apps/voxhelm/site/var/models"
voxhelm_piper_voice_dir: "/opt/apps/voxhelm/site/var/piper"
voxhelm_piper_voices:
  - "en_US-lessac-medium"
  - "de_DE-thorsten-high"
voxhelm_piper_default_voice: "en_US-lessac-medium"
voxhelm_piper_language_voices:
  en: "en_US-lessac-medium"
  en_US: "en_US-lessac-medium"
  de: "de_DE-thorsten-high"
  de_DE: "de_DE-thorsten-high"
voxhelm_wyoming_stt_enabled: true
voxhelm_wyoming_stt_host: "0.0.0.0"
voxhelm_wyoming_stt_port: 10300
voxhelm_wyoming_stt_backend: "mlx"
voxhelm_wyoming_stt_model: ""
voxhelm_wyoming_stt_language: ""
voxhelm_wyoming_stt_languages:
  - "de"
  - "en"
voxhelm_wyoming_stt_prompt: ""
voxhelm_wyoming_stt_normalize_transcript: true
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

- The Wyoming listener on `10300` now exposes both STT and TTS backed by Voxhelm.
- The launchd label and helper script retain the legacy `-stt` suffix for continuity, but the runtime
  serves both speech directions.
- `voxhelm_wyoming_stt_backend` defaults to `mlx` because it performed materially
  better than the current `whisper.cpp` setup on short Home Assistant commands
  with trailing silence.
- `voxhelm_wyoming_stt_model`, `voxhelm_wyoming_stt_language`, and
  `voxhelm_wyoming_stt_prompt` can be used to pin the interactive listener to a
  specific model, language, or prompt without changing the main HTTP/batch lane.
- `voxhelm_wyoming_stt_normalize_transcript` trims a small set of leading
  filler words such as `okay` / `und` from Wyoming transcripts before they are
  returned to Home Assistant. This is enabled by default because the built-in
  German Assist parser is materially less tolerant of those prefixes than the
  English one.
- `voxhelm_stt_debug_logging` enables one structured log line per transcription
  containing the input audio shape, requested and resolved backend/model/language,
  and transcript preview. When normalization changes the transcript, the debug
  log also includes the raw transcript for comparison. Leave it off unless you
  are actively tuning or debugging.
- Piper voice files are downloaded during deploy into `voxhelm_piper_voice_dir`.
- `voxhelm_piper_language_voices` maps requested language codes such as `en` / `de`
  to installed Piper voice IDs for both Wyoming TTS and HTTP or batch synthesis.
- There is no cross-process lane scheduler yet. The Wyoming sidecar has its own
  process and its own in-process serialization, but it can still contend with
  the HTTP API and batch worker for CPU, RAM, and model cache use on `studio`.
- The role verifies the sidecar by checking the launchd unit state and waiting
  for the configured TCP port to listen locally on the target host.

## License

MIT
