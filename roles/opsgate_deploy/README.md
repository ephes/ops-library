# opsgate_deploy

Deploy OpsGate on macOS (`launchd` host model) with the Phase 2 control service.

## What this role does

- Creates and manages both required users:
  - `control_service_user` for API/UI process execution
  - `ops` for runner/tmux execution
- Creates spec-aligned execution layout:
  - `ops_home_dir` (default `/Users/ops`)
  - `execution_data_dir` (default `{{ ops_home_dir }}/remediation`)
  - `tickets_dir` (default `{{ execution_data_dir }}/jobs`)
  - `session_artifacts_dir` (default `{{ execution_data_dir }}/sessions`)
- Syncs local app source (`opsgate_source_path`) into `{{ opsgate_app_dir }}`
- Installs runtime dependencies using `uv sync --frozen --no-dev`
- Wires optional `ops` credentials (SSH private/public key, SOPS age key, GitHub token)
- Renders API/runner env files under `/etc/opsgate`
- Writes tmux defaults for the `ops` runner account
- Renders two LaunchDaemons:
  - `de.wersdoerfer.opsgate.api` as `control_service_user`
  - `de.wersdoerfer.opsgate.runner` as `ops`

The runner daemon remains placeholder/stub in Phase 2; only API/UI is expected to be activated.

## Important defaults

- `opsgate_launchd_manage_state: false`
- `opsgate_launchd_start_services: false`
- `opsgate_api_launchd_manage_state: "{{ opsgate_launchd_manage_state }}"`
- `opsgate_runner_launchd_manage_state: "{{ opsgate_launchd_manage_state }}"`
- `opsgate_api_launchd_start_service: "{{ opsgate_launchd_start_services }}"`
- `opsgate_runner_launchd_start_service: "{{ opsgate_launchd_start_services }}"`

## macOS runtime path note

- `opsgate_runtime_dir` defaults to `/usr/local/var/opsgate/run` (persistent on macOS).
- Avoid `/var/run/opsgate` for persistent assumptions because `/var/run` is boot-volatile on macOS.

## Workspace placeholder note

- The role pre-creates:
  - `{{ ops_home_dir }}/workspaces/ops-control`
  - `{{ ops_home_dir }}/workspaces/ops-library`
- Future clone steps should use explicit target paths (for example `git -C <path> ...`) to avoid accidental
  conflicts with implicit clone destination behavior.

## Key Variables

```yaml
ops_user: "ops"
control_service_user: "control_service_user"
ops_home_dir: "/Users/ops"
execution_data_dir: "{{ ops_home_dir }}/remediation"
tickets_dir: "{{ execution_data_dir }}/jobs"
session_artifacts_dir: "{{ execution_data_dir }}/sessions"
opsgate_source_path: "/Users/jochen/projects/opsgate"
opsgate_uv_bin: "uv"

opsgate_ui_password_bcrypt: "CHANGEME_BCRYPT_HASH"
opsgate_submit_token_openclaw: "CHANGEME_OPENCLAW_SUBMIT_TOKEN"
opsgate_submit_token_nyxmon: "CHANGEME_NYXMON_SUBMIT_TOKEN"
opsgate_submit_token_operator: "CHANGEME_OPERATOR_SUBMIT_TOKEN"
opsgate_runner_token: "CHANGEME_RUNNER_TOKEN"
opsgate_session_secret: "CHANGEME_OPSGATE_SESSION_SECRET"
opsgate_require_tailscale_context: true
opsgate_allowed_cidrs:
  - "127.0.0.1/32"
  - "::1/128"
  - "100.64.0.0/10"
  - "fd7a:115c:a1e0::/48"

opsgate_ops_ssh_private_key: ""
opsgate_ops_age_private_key: ""
opsgate_ops_github_username: ""
opsgate_ops_github_token: ""

opsgate_launchd_manage_state: true
opsgate_api_launchd_manage_state: true
opsgate_runner_launchd_manage_state: false
opsgate_api_launchd_start_service: true
opsgate_runner_launchd_start_service: false
```

See `defaults/main.yml` for the full variable reference.

## Example playbook

```yaml
- name: Deploy OpsGate control service (Phase 2)
  hosts: macstudio
  become: true
  roles:
    - role: local.ops_library.opsgate_deploy
      vars:
        opsgate_source_path: "/Users/jochen/projects/opsgate"
        opsgate_launchd_manage_state: true
        opsgate_api_launchd_manage_state: true
        opsgate_runner_launchd_manage_state: false
        opsgate_api_launchd_start_service: true
        opsgate_runner_launchd_start_service: false
```
