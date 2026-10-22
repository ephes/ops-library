# voxhelm_remote_worker_deploy

Deploy a Voxhelm remote transcription worker on macOS. The role installs the
`voxhelm` console script from public PyPI with `uv tool install`, renders a
secret environment file, and runs `voxhelm-remote-worker` under launchd.
Run the role with facts enabled; it validates the macOS target and current
Ansible user before touching Homebrew or launchd.

## What This Role Manages

- public-PyPI installation of a pinned `voxhelm[diarization]` version
- a deployment transcript at `voxhelm_remote_worker_install_transcript_path`
- `/etc/voxhelm-remote-worker/worker.env`
- `/etc/voxhelm-remote-worker/worker-launcher.sh`
- a launchd `LaunchDaemon` for the remote worker
- service-user-owned launchd logs plus local model-cache and working directories

## Important Defaults

```yaml
voxhelm_remote_worker_public_index_url: "https://pypi.org/simple"
voxhelm_remote_worker_package_name: "voxhelm"
voxhelm_remote_worker_package_version: "0.1.0"
voxhelm_remote_worker_package_extras:
  - "diarization"
voxhelm_remote_worker_force_install: false
voxhelm_remote_worker_launcher_path: "/etc/voxhelm-remote-worker/worker-launcher.sh"
voxhelm_remote_worker_id: "atlas"
voxhelm_remote_worker_allowed_url_hosts: []
voxhelm_remote_worker_private_url_hosts: []  # allowlisted hosts that may resolve to private IPs
voxhelm_remote_worker_caffeinate_enabled: true
voxhelm_remote_worker_caffeinate_args:
  - "-i"
  - "-m"
  - "-s"
voxhelm_remote_worker_whispercpp_model_source: ""
voxhelm_remote_worker_artifact_backend: "s3"
voxhelm_remote_worker_diarization_backend: "pyannote"
```

`voxhelm_remote_worker_service_user`, `voxhelm_remote_worker_base_url`,
`voxhelm_remote_worker_token`, S3 credentials, and the Hugging Face token must
come from the private control repo or encrypted secrets. Do not put those values
in ops-library.

`voxhelm_remote_worker_allowed_url_hosts` must include the same media hosts that
the control plane accepts for URL jobs; workers re-validate claim input before
downloading media.

`voxhelm_remote_worker_private_url_hosts` lists the hosts that may resolve to
private addresses (for example an S3 endpoint on the home network). Workers
apply the same redirect and private-address checks as the control plane, so
set it to the control plane's `voxhelm_private_url_hosts`. It is rendered as
`VOXHELM_PRIVATE_URL_HOSTS` (comma-separated) only when non-empty and must be a
list of host names without commas or whitespace; validation rejects anything
else before deployment.

The launcher wraps the worker with `caffeinate -ims` by default so unattended
macOS hosts do not idle-sleep or spin down disks during long Metal/CPU
transcription and diarization jobs, while still allowing the display to sleep.
Add `-d` to `voxhelm_remote_worker_caffeinate_args` only on hosts whose displays
must remain awake.

Set `voxhelm_remote_worker_whispercpp_model_source` when a host already has the
configured whisper.cpp model elsewhere. The role links that file into the
worker model cache without replacing an existing cached model.

### Parakeet (known-speaker jobs)

`voxhelm_remote_worker_parakeet_enabled: true` installs NVIDIA Parakeet TDT for
Voxhelm's known-speaker jobs (Voxhelm 0.1.9 or later):

- `uv tool install --python 3.13 parakeet-mlx==<voxhelm_remote_worker_parakeet_package_version>`
  as the service user (Voxhelm itself needs Python 3.14 and runs the CLI as a
  child process); skipped when that version is already installed, and the
  worker restarts after an install.
- `config.json` and `model.safetensors` of
  `voxhelm_remote_worker_parakeet_model_repo` at the pinned commit
  `voxhelm_remote_worker_parakeet_model_revision` (2.5 GB), downloaded with the
  `hf` CLI from the parakeet-mlx tool environment into
  `<model_dir>.partial`, checked against
  `voxhelm_remote_worker_parakeet_model_sha256`, and only then moved to
  `voxhelm_remote_worker_parakeet_model_dir` (by default
  `<model cache>/parakeet/<commit>`) with a `VOXHELM_MODEL_REVISION` file
  recording the repo, commit and checksum. A directory whose files are all
  there and whose marker matches the configured pin is not downloaded again;
  anything else is replaced. A new commit gets a new directory by default, and
  old ones are left in place.
- The `VOXHELM_PARAKEET_*` settings in `worker.env` (CLI path, model directory
  and name, chunk and overlap seconds, optional maximum sentence seconds,
  timeout). They are not rendered while the switch is off, so the worker does
  not advertise Parakeet.

The worker advertises the `parakeet` backend only while the CLI and both model
files are present, re-checked on every heartbeat. Jobs reach it only after the
control plane sets `voxhelm_known_speaker_stt_backend: "parakeet"`
(`voxhelm_deploy`); until then nothing changes.

### `ad-analysis-v1` profile (Delve's server ad analysis)

Off by default (`voxhelm_remote_worker_ad_analysis_enabled: false`). The
profile (Voxhelm D-26 to D-29) runs Parakeet with its own fixed settings, then
the German drift check and the chapter windows with whisper large-v3-turbo,
and measures the media with ffprobe. A worker advertises
`capabilities.profiles: ["ad-analysis-v1"]` only while all of these resolve
(checked at every heartbeat); a profile job waits for such a worker and never
falls back to another engine. When enabled, the role

- requires `voxhelm_remote_worker_parakeet_enabled` (the CLI and the pinned
  model above);
- installs `voxhelm_remote_worker_ad_analysis_brew_packages` (`whisper-cpp`,
  `ffmpeg`) when missing and fails unless `voxhelm_remote_worker_whispercpp_bin`
  and `voxhelm_remote_worker_ffprobe_bin` exist;
- downloads `ggml-large-v3-turbo.bin` at a pinned Hugging Face commit into the
  worker's model cache and verifies its SHA-256
  (`voxhelm_remote_worker_window_model_sha256`, the hash Voxhelm pins as
  `WINDOW_MODEL_SHA256`; any other file leaves the profile unavailable), or, with
  `voxhelm_remote_worker_window_model_source`, checks an existing file's hash
  and links it there;
- renders `VOXHELM_WINDOW_MODEL`, `VOXHELM_WINDOW_TIMEOUT_SECONDS` and
  `VOXHELM_FFPROBE_BIN`, and restarts the worker when the model or the env
  file changed.

The installed `voxhelm` package must be a release that has the profile
(`voxhelm_remote_worker_package_version`); an older worker never advertises it.

## Example

```yaml
- name: Deploy Atlas Voxhelm worker
  hosts: atlas
  become: true
  roles:
    - role: local.ops_library.uv_install
    - role: local.ops_library.voxhelm_remote_worker_deploy
      vars:
        voxhelm_remote_worker_service_user: "jochen"
        voxhelm_remote_worker_brew_user: "jochen"
        voxhelm_remote_worker_base_url: "http://voxhelm-control.example.test:8787"
        voxhelm_remote_worker_id: "atlas"
        voxhelm_remote_worker_token: "{{ service_secrets.worker_token_atlas }}"
```

Workers should normally connect directly to the Voxhelm control plane over the
private network. The public Traefik edge keeps `/v1/internal` blocked unless a
separate worker-internal allowlist is deliberately configured.
