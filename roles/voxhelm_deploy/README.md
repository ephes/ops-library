# voxhelm_deploy

Deploy Voxhelm on macOS using `uv`, `uvicorn`, and a launchd `LaunchDaemon`.

## Description

This role deploys the Voxhelm service to the `studio` Mac Studio. It syncs the
local source tree, installs dependencies with `uv sync --frozen --no-dev`
plus configured optional extras, renders a shell environment file, applies
Django migrations, creates launcher scripts for the HTTP API and the Django
Tasks worker, installs launchd plists, and verifies both the HTTP health
endpoint and worker launchd state locally on the target host.

Current default runtime:

- one `uvicorn` HTTP API process
- one Django Tasks `db_worker` process
- one Wyoming STT/TTS sidecar process on port `10300`
- optional WhisperKit local-server sidecar on port `50060` when explicitly enabled
- optional hourly `manage.py prune_job_artifacts` launchd job, off by default
  (see "Job Artifact Pruning" below)
- `whisper.cpp` as the default STT backend on `studio`, with `mlx-whisper` as fallback
- `mlx-whisper` as the default Wyoming STT backend for short interactive speech
- `piper` as the default TTS backend on `studio`
- optional Kokoro ONNX TTS backend and automatic de/en language routing, both
  disabled by default
- host-wide lane scheduling enabled by default for local inference on `studio`
- speaker diarization disabled by default, with optional pyannote support
- bearer-token authentication via environment variables
- filesystem artifact storage by default, with S3/MinIO-compatible env vars available
- no Traefik dependency; the service binds directly on the configured port

## Requirements

- macOS target host
- `uv` installed on the target host
- Hugging Face token and accepted pyannote model access when
  `voxhelm_diarization_backend: "pyannote"`
- Ansible collection:
  - `ansible.posix`

## Required Variables

```yaml
voxhelm_source_path: "/Users/jochen/projects/voxhelm"
voxhelm_django_secret_key: "replace-me"
voxhelm_bearer_tokens_env: "archive=replace-me"
voxhelm_bootstrap_operator_username: "jochen"
voxhelm_bootstrap_operator_password: "replace-me"
```

## Optional Variables

`voxhelm_bootstrap_operator_email` is optional and may be empty. The bootstrap
username and password are required at deploy time even though they also appear
in `defaults/main.yml` with sentinel placeholders.

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
voxhelm_whisperkit_enabled: false
voxhelm_whisperkit_cli_bin: "/opt/homebrew/bin/whisperkit-cli"
voxhelm_whisperkit_host: "127.0.0.1"
voxhelm_whisperkit_port: 50060
voxhelm_whisperkit_base_url: "http://127.0.0.1:50060/v1"
voxhelm_whisperkit_model: "large-v3-v20240930"
voxhelm_whisperkit_audio_encoder_compute_units: "cpuAndGPU"
voxhelm_whisperkit_text_decoder_compute_units: "cpuAndGPU"
voxhelm_whisperkit_concurrent_worker_count: 8
voxhelm_whisperkit_chunking_strategy: "vad"
voxhelm_whisperkit_timeout_seconds: 900
voxhelm_stt_debug_logging: false
voxhelm_python_version: "3.14.5"
voxhelm_diarization_backend: "none"
voxhelm_pyannote_model: "pyannote/speaker-diarization-3.1"
voxhelm_pyannote_device: "auto"
voxhelm_huggingface_token: ""
voxhelm_uv_extras: []
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
voxhelm_tts_kokoro_enabled: false
voxhelm_tts_language_routing_enabled: false
voxhelm_kokoro_model_dir: "/opt/apps/voxhelm/site/var/kokoro"
voxhelm_kokoro_models:
  kokoro-af_heart:
    model_file: "kokoro-v1.0.onnx"
    voicepack_file: "voices-v1.0.bin"
    voicepack_key: "af_heart"
    phoneme_language: "en-us"
  kokoro-martin:
    model_file: "kokoro-martin.onnx"
    voicepack_file: "voices-martin.npz"
    voicepack_key: "martin"
    phoneme_language: "de"
voxhelm_kokoro_default_voice: ""
voxhelm_tts_language_voices:
  de: "kokoro-martin"
  en: "kokoro-af_heart"
voxhelm_espeak_library: "/opt/homebrew/lib/libespeak-ng.dylib"
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
voxhelm_lane_scheduler_enabled: true
voxhelm_lane_scheduler_dir: "/opt/apps/voxhelm/site/var/lane-scheduler"
voxhelm_lane_scheduler_stale_seconds: 1800
voxhelm_lane_scheduler_interactive_slots: 1
voxhelm_lane_scheduler_non_interactive_slots: 1
voxhelm_bootstrap_operator_username: "CHANGEME"
voxhelm_bootstrap_operator_email: ""
voxhelm_bootstrap_operator_password: "CHANGEME"
voxhelm_allowed_hosts:
  - "studio.tailde2ec.ts.net"
  - "studio"
  - "localhost"
  - "127.0.0.1"
voxhelm_csrf_trusted_origins: []
voxhelm_allowed_url_hosts: []
voxhelm_trusted_http_hosts: []
voxhelm_uvicorn_log_level: "info"
voxhelm_prune_enabled: false
voxhelm_prune_dry_run: true
voxhelm_prune_interval_seconds: 3600
# Rendered into voxhelm.env only when set; empty/[] keeps Voxhelm's default.
voxhelm_source_artifact_retention_seconds: ""  # Voxhelm default 86400
voxhelm_job_metadata_retention_seconds: ""     # Voxhelm default 7776000 (90 days); 0 disables
voxhelm_staged_input_retention_seconds: ""     # Voxhelm default 86400
voxhelm_wyoming_stt_max_audio_seconds: ""      # Voxhelm default 120
voxhelm_private_url_hosts: []                  # allowlisted hosts that may resolve to private IPs
```

The optional retention and Wyoming values must be non-negative whole numbers;
`voxhelm_private_url_hosts` must be a list of host names without commas or
whitespace (it is rendered as `VOXHELM_PRIVATE_URL_HOSTS`, comma-separated). Validation rejects anything else
before deployment.

For the full list, see `defaults/main.yml`.

## Operator login through HTTPS ingress

`voxhelm_csrf_trusted_origins` supplies the app's existing
`VOXHELM_CSRF_TRUSTED_ORIGINS` environment setting as a comma-separated list.
Use a list of scheme-qualified HTTP(S) origins such as `https://voxhelm.example.com`.
Validation rejects bare strings, missing schemes, paths, whitespace, and commas
before deployment changes are made.
The default `[]` renders an empty environment value. Voxhelm's `env_list`
parser filters blank entries, so this has the same empty-list behavior as an
unset variable. This setting applies
to Django's browser/session CSRF checks; it does not replace API bearer-token
checks or `voxhelm_allowed_hosts`. Voxhelm already honors forwarded HTTPS in
its Django settings.

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
        voxhelm_csrf_trusted_origins:
          - "https://voxhelm.example.com"
        voxhelm_bootstrap_operator_username: "{{ service_secrets.bootstrap_operator_username }}"
        voxhelm_bootstrap_operator_email: "{{ service_secrets.bootstrap_operator_email }}"
        voxhelm_bootstrap_operator_password: "{{ service_secrets.bootstrap_operator_password }}"
        voxhelm_diarization_backend: "pyannote"
        voxhelm_pyannote_model: "pyannote/speaker-diarization-3.1"
        voxhelm_huggingface_token: "{{ service_secrets.huggingface_token }}"
```

## Bootstrap Operator

- The role runs `python manage.py bootstrap_operator` after migrations on every deploy.
- Bootstrap credentials should come from the private control repo, typically `ops-control/secrets/prod/voxhelm.yml`.
- The in-app command is idempotent: first deploy creates the operator, later deploys update the matching account's password, email, `is_staff`, and `is_active` fields.
- The role passes credentials as task-scoped environment variables for that one-shot command and does not persist the operator password in `voxhelm.env`.

## Speaker Diarization Notes

- `voxhelm_diarization_backend` defaults to `none`; requested diarization jobs
  fail clearly unless a backend is configured.
- The role creates `.venv` with a uv-managed `voxhelm_python_version` interpreter
  instead of the host's Homebrew Python. If an existing virtualenv points at a
  different base executable, the role recreates it before running `uv sync`.
- Setting `voxhelm_diarization_backend: "pyannote"` makes the role install the
  Voxhelm optional dependency extra with `uv sync --frozen --no-dev --extra diarization`.
- The role renders `VOXHELM_DIARIZATION_BACKEND`, `VOXHELM_PYANNOTE_MODEL`,
  `VOXHELM_PYANNOTE_DEVICE`, `VOXHELM_HUGGINGFACE_TOKEN`, and `HF_TOKEN` into `/etc/voxhelm/voxhelm.env`.
  The env file remains `root:wheel` and `0640`, and the template task uses
  `no_log: true`.
- The role also renders the transcription execution mode. The default
  `voxhelm_transcription_execution_mode: django_tasks` preserves local studio
  execution. Setting `voxhelm_transcription_execution_mode: remote_pull`
  requires `voxhelm_worker_tokens_env` and complete S3 artifact settings so
  remote workers can claim jobs and upload attempt-scoped artifacts.
- The HTTP API, Django Tasks worker, and Wyoming sidecar all source the same
  env file through their launcher scripts. The Hugging Face token is not written
  directly into launchd plist files.
- The token should come from encrypted private control-repo secrets, not from
  this public collection.
- Accept Hugging Face access for `pyannote/speaker-diarization-3.1`,
  `pyannote/speaker-diarization-community-1`, and any gated dependency reported
  by pyannote before first production use.
- The first diarization run downloads model weights and can take time. Long
  podcast episodes are expensive; use batch jobs and inspect the worker logs.

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
- `voxhelm_whisperkit_enabled` installs `whisperkit-cli`, renders a dedicated
  launchd unit, and exposes the backend to Voxhelm's accepted-model surface.
  Leave it `false` unless you explicitly want the experimental backend on
  `studio`.
- `voxhelm_whisperkit_model`, compute-unit knobs, worker count, and chunking
  strategy map directly to `whisperkit-cli serve` so the tuned `studio`
  configuration can be preserved in deploy config rather than in ad-hoc shell
  history.
- WhisperKit remains non-default on purpose. The benchmark re-evaluation showed
  it is competitive on `studio`, but the tuned long-form run still logged a
  Metal GPU recovery error.
- `voxhelm_wyoming_stt_normalize_transcript` trims a small set of leading
  filler words such as `okay` / `und` from Wyoming transcripts before they are
  returned to Home Assistant. This is enabled by default because the built-in
  German Assist parser is materially less tolerant of those prefixes than the
  English one.
- `voxhelm_lane_scheduler_enabled` enables the host-wide admission gate shared
  by the HTTP API, Django Tasks worker, and Wyoming sidecar.
- `voxhelm_lane_scheduler_dir` stores the shared scheduler state on local disk
  (one file per admitted holder under `holders/`).
- `voxhelm_lane_scheduler_stale_seconds` defaults to `1800` so a crashed holder
  can be reclaimed without risking false expiry during long-running local
  inference. Lower this only if the runtime also refreshes the lease while work
  is active. Recovery applies to every holder file independently.
- `voxhelm_lane_scheduler_interactive_slots` (default `1`) reserves that many
  slots for the Wyoming (interactive) lane; non-interactive work never occupies
  them. `voxhelm_lane_scheduler_non_interactive_slots` (default `1`) caps how
  many HTTP/batch inferences may run at once. Keep both at `1` on `studio`
  (Voxhelm decision D-24): one long HTTP transcription and one Wyoming request
  then share the GPU instead of the Wyoming request waiting. Set the interactive
  count to `0` to fall back to the original single-slot serialization.
- `voxhelm_stt_debug_logging` enables one structured log line per transcription
  containing the input audio shape, requested and resolved backend/model/language,
  and transcript preview. When normalization changes the transcript, the debug
  log also includes the raw transcript for comparison. Leave it off unless you
  are actively tuning or debugging.
- Piper voice files are downloaded during deploy into `voxhelm_piper_voice_dir`.
- `voxhelm_piper_language_voices` maps requested language codes such as `en` / `de`
  to installed Piper voice IDs for both Wyoming TTS and HTTP or batch synthesis.
- The scheduler is cooperative, not preemptive: it never interrupts running
  work. With the default `1 + 1` slots a Wyoming turn is admitted immediately
  while one HTTP or batch inference runs; it only waits when both slots are
  taken. Only separate-process backends (`whisper-cli`, WhisperKit) overlap; the
  `mlx` Wyoming backend runs in the sidecar process and overlaps a `whisper-cli`
  run from the HTTP process safely. The sync transcription endpoint terminates
  its `whisper-cli` child when the HTTP client disconnects.
- Deploys restart all three launchd services in one run. The holder layout
  changed with D-24 (`holders/` directory instead of `holder.json`); during the
  seconds between the sequential restarts the concurrency bound can be exceeded
  by one holder, which is a transient GPU-share effect only.
- The role verifies the sidecar by checking the launchd unit state and waiting
  for the configured TCP port to listen locally on the target host.

## Job Artifact Pruning

Voxhelm's `manage.py prune_job_artifacts` (D-09) deletes expired job source
media, extracted audio, queued artifact deletions and, after
`VOXHELM_JOB_METADATA_RETENTION_SECONDS`, old terminal job rows. Transcript and
speech artifacts are never pruned. The role can schedule it on the control
plane as a fourth launchd job, `de.wersdoerfer.voxhelm-prune`
(`voxhelm_prune_label`), which runs `prune.sh` every
`voxhelm_prune_interval_seconds` (default `3600`, minimum `60`) through
`StartInterval`; `RunAtLoad` and `KeepAlive` are false. `prune.sh` sources
`voxhelm.env` like the worker. Output goes to
`/var/log/voxhelm/voxhelm-prune.log` and `voxhelm-prune.err.log`. A deploy loads
the job but never kickstarts it, and the source sync keeps `prune.sh` (it is
excluded from the `delete: true` rsync when it lives in `voxhelm_app_dir`). `voxhelm_remote_worker_deploy` never schedules
pruning.

The job is **off by default** (`voxhelm_prune_enabled: false`): the first real
run deletes the whole backlog of expired intermediates and old job rows at
once. With `voxhelm_prune_enabled: false` the role also unloads a prune job
left by an earlier deploy (stopping a run in progress), fails if launchd still
has it loaded, and only then removes its plist and script. With
`voxhelm_launchd_manage_state: false` the role leaves launchd and these files
alone. `voxhelm_prune_dry_run`
defaults to `true`, so enabling the job alone only logs what each run would
delete.

To enable it:

1. Preview the backlog by hand on the control plane:

   ```bash
   sudo bash -c 'set -a; source /etc/voxhelm/voxhelm.env; set +a; \
     cd /opt/apps/voxhelm/site && .venv/bin/python manage.py prune_job_artifacts --dry-run'
   ```

2. Optionally set `voxhelm_source_artifact_retention_seconds` /
   `voxhelm_job_metadata_retention_seconds`, then set
   `voxhelm_prune_enabled: true` (keeping `voxhelm_prune_dry_run: true`) and
   deploy. Check `voxhelm-prune.log` after the next hourly run.
3. When the dry-run output looks right, set `voxhelm_prune_dry_run: false` and
   deploy again. The next scheduled run deletes for real; to run it right away,
   use `sudo launchctl kickstart system/de.wersdoerfer.voxhelm-prune`.

To switch it off again, set `voxhelm_prune_enabled: false` and deploy.

## Kokoro TTS and Language Routing Notes

- The optional Kokoro ONNX TTS backend adds an English voice (`kokoro-af_heart`,
  official Kokoro v1.0) and a German fine-tune (`kokoro-martin`) alongside Piper.
  It is disabled by default; Piper stays installed as the fallback and rollback
  path.
- `voxhelm_tts_kokoro_enabled` is the single flag that gates BOTH the `kokoro` uv
  extra and Kokoro model registration. When it is `false`, `uv sync` omits the
  extra AND the env template renders no `VOXHELM_KOKORO_*` variables, so Kokoro
  voices are never advertised in Wyoming `describe` nor dispatchable. `validate.yml`
  asserts these two cannot diverge (a language mapped to a `kokoro-*` voice fails
  fast unless Kokoro is enabled and the voice is configured).
- When enabled, the role installs `espeak-ng` via Homebrew (Kokoro phonemizes both
  languages through espeak-ng) and downloads the checksum-pinned model artifacts
  into `voxhelm_kokoro_model_dir`. Downloads use `get_url` with a `sha256` checksum,
  so they are idempotent and integrity-verified — an already-present, matching file
  is not re-fetched. The int8 official model (`kokoro-v1.0.int8.onnx`) is
  provisioned alongside the full model so the latency fallback is a config-only
  switch.
- `voxhelm_kokoro_models` maps a registry voice key (convention `kokoro-<voicepack_key>`)
  to `model_file`, `voicepack_file`, `voicepack_key` (the embedding selected inside
  the pack), and `phoneme_language` (espeak language, e.g. `en-us` / `de`). It is
  rendered into `VOXHELM_KOKORO_MODELS` in the compact
  `voice_key=model:voicepack:voicepack_key:language` encoding that voxhelm parses.
  Every referenced `model_file`/`voicepack_file` must appear in
  `voxhelm_kokoro_artifacts` (validated).
- `voxhelm_kokoro_default_voice` is optional; when set it must be a configured model
  key. `voxhelm_espeak_library` overrides the libespeak-ng shared library and
  defaults to the Homebrew dylib at `/opt/homebrew/lib/libespeak-ng.dylib`.
- `voxhelm_tts_language_routing_enabled` gates the `routing` uv extra
  (`lingua-language-detector`) and renders `VOXHELM_TTS_LANGUAGE_ROUTING`. When on,
  `voxhelm_tts_language_voices` (rendered into `VOXHELM_TTS_LANGUAGE_VOICES`) maps a
  detected language to a registry voice across all backends; outgoing TTS text is
  language-detected and the mapped voice overrides the pipeline-pinned voice.
  Routing is independently toggleable from Kokoro, but mapping a language to a
  `kokoro-*` voice requires Kokoro enabled.
- Rollback is config-only and order matters: set
  `voxhelm_tts_language_routing_enabled: false` first to stop automatic Kokoro use
  (HA pipeline voices are Piper voices), then
  `voxhelm_tts_kokoro_enabled: false` to remove Kokoro voices entirely.

## License

MIT
