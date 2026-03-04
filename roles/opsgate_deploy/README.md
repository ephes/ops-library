# opsgate_deploy

Bootstrap OpsGate Phase 1 runtime prerequisites on macOS (`launchd` host model).

This role intentionally does not implement OpsGate application business logic (API or runner code).
It establishes the account model, filesystem layout, environment wiring, tmux defaults, and launchd
plist placeholders required for Phase 2/3 implementation.

## What this role does

- Creates and manages both required users:
  - `control_service_user` for API/UI process execution
  - `ops` for runner/tmux execution
- Creates spec-aligned execution layout:
  - `ops_home_dir` (default `/Users/ops`)
  - `execution_data_dir` (default `{{ ops_home_dir }}/remediation`)
  - `tickets_dir` (default `{{ execution_data_dir }}/jobs`)
  - `session_artifacts_dir` (default `{{ execution_data_dir }}/sessions`)
- Wires optional `ops` credentials (SSH private/public key, SOPS age key, GitHub token)
- Renders API/runner env files under `/etc/opsgate`
- Writes tmux defaults for the `ops` runner account
- Renders two LaunchDaemons:
  - `de.wersdoerfer.opsgate.api` as `control_service_user`
  - `de.wersdoerfer.opsgate.runner` as `ops`

## Important Phase 1 defaults

- `opsgate_launchd_manage_state: false` (only renders plists unless enabled)
- `opsgate_launchd_start_services: false` (prevents placeholder daemons from being started)

This keeps Phase 1 safe while API/runner binaries are not implemented yet.

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

opsgate_ui_password_bcrypt: "CHANGEME_BCRYPT_HASH"
opsgate_submit_token_openclaw: "CHANGEME_OPENCLAW_SUBMIT_TOKEN"
opsgate_submit_token_nyxmon: "CHANGEME_NYXMON_SUBMIT_TOKEN"
opsgate_submit_token_operator: "CHANGEME_OPERATOR_SUBMIT_TOKEN"
opsgate_runner_token: "CHANGEME_RUNNER_TOKEN"

opsgate_ops_ssh_private_key: ""
opsgate_ops_age_private_key: ""
opsgate_ops_github_username: ""
opsgate_ops_github_token: ""

opsgate_launchd_manage_state: false
opsgate_launchd_start_services: false
```

See `defaults/main.yml` for the full variable reference.

## Example playbook

```yaml
- name: Deploy OpsGate Phase 1 bootstrap
  hosts: macstudio
  become: true
  roles:
    - role: local.ops_library.opsgate_deploy
```
