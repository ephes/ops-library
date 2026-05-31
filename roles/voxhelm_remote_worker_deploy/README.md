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
- a launchd `LaunchDaemon` for the remote worker
- local log, model-cache, and working directories

## Important Defaults

```yaml
voxhelm_remote_worker_public_index_url: "https://pypi.org/simple"
voxhelm_remote_worker_package_name: "voxhelm"
voxhelm_remote_worker_package_version: "0.1.0"
voxhelm_remote_worker_package_extras:
  - "diarization"
voxhelm_remote_worker_force_install: false
voxhelm_remote_worker_id: "atlas"
voxhelm_remote_worker_artifact_backend: "s3"
voxhelm_remote_worker_diarization_backend: "pyannote"
```

`voxhelm_remote_worker_service_user`, `voxhelm_remote_worker_base_url`,
`voxhelm_remote_worker_token`, S3 credentials, and the Hugging Face token must
come from the private control repo or encrypted secrets. Do not put those values
in ops-library.

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
