# opsgate_deploy

Deploy OpsGate on macOS (`launchd` host model) with the Phase 4B control service + runner baseline.

## What this role does

- Creates and manages both required users:
  - `control_service_user` for API/UI process execution
  - `ops` for runner/tmux execution
- Creates spec-aligned execution layout:
  - `ops_home_dir` (default `/Users/ops`)
  - `execution_data_dir` (default `{{ ops_home_dir }}/remediation`)
  - `tickets_dir` (default `{{ execution_data_dir }}/jobs`)
  - `session_artifacts_dir` (default `{{ execution_data_dir }}/sessions`)
- Syncs local app source (`opsgate_source_path`) into:
  - `{{ opsgate_app_dir }}` (API/UI runtime, `control_service_user`)
  - `{{ opsgate_runner_app_dir }}` (runner runtime, `ops`)
- Installs runtime dependencies using `uv sync --frozen --no-dev` for both runtimes
- Wires optional `ops` credentials (machine SSH key, dedicated GitHub SSH key, SOPS age key, GitHub token)
- Optionally clones/updates managed `ops` workspaces (for example `ops-control`, `ops-library`) once GitHub-side access exists
- Renders API/runner env files under `/etc/opsgate`
- Writes tmux defaults for the `ops` runner account
- Renders two LaunchDaemons:
  - `de.wersdoerfer.opsgate.api` as `control_service_user`
  - `de.wersdoerfer.opsgate.runner` as `ops`
- Leaves HTTPS ingress to a separate Traefik-facing role on the edge host

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

- The role pre-creates placeholder directories for the repository names listed in
  `opsgate_ops_workspace_repositories`.
- Future clone steps should use explicit target paths (for example `git -C <path> ...`) to avoid accidental
  conflicts with implicit clone destination behavior.

## Managed workspace bootstrap

The role can optionally clone/update a managed set of repositories for the `ops` user.

Default behavior:

- `opsgate_ops_manage_workspace_repos: false`
- workspace directories are created as placeholders only

When enabled:

- the role ensures a `known_hosts` file exists for `ops`
- it adds the GitHub ED25519 host key when any configured repo uses a GitHub SSH URL
- it clones/updates each repository under `{{ ops_home_dir }}/workspaces/<name>`
- it does not force-reset dirty worktrees during updates

This is intended for the OpsGate implementer workflow, where the runner-side `ops` account needs durable
repo access for tickets that modify source and deploy through the normal path.

Important prerequisite:

- the deployed GitHub SSH key or GitHub credential must already be authorized for the target repositories
- enabling managed workspace repos before GitHub-side access exists will cause the clone/update task to fail

## Key Variables

```yaml
ops_user: "ops"
control_service_user: "control_service_user"
ops_home_dir: "/Users/ops"
execution_data_dir: "{{ ops_home_dir }}/remediation"
tickets_dir: "{{ execution_data_dir }}/jobs"
session_artifacts_dir: "{{ execution_data_dir }}/sessions"
opsgate_source_path: "/Users/jochen/projects/opsgate"
opsgate_app_dir: "/Users/control_service_user/opsgate"
opsgate_runner_app_dir: "/Users/ops/opsgate"
opsgate_uv_bin: "uv"

opsgate_ui_password_bcrypt: "CHANGEME_BCRYPT_HASH"
opsgate_trust_proxy_headers: false
opsgate_session_cookie_secure: false
# Optional in current slice
opsgate_submit_token_openclaw: ""
opsgate_submit_token_nyxmon: "CHANGEME_NYXMON_SUBMIT_TOKEN"
opsgate_submit_token_operator: "CHANGEME_OPERATOR_SUBMIT_TOKEN"
opsgate_runner_token: "CHANGEME_RUNNER_TOKEN"
opsgate_session_secret: "CHANGEME_OPSGATE_SESSION_SECRET"
opsgate_runner_api_base_url: "http://127.0.0.1:8711"
opsgate_runner_host: "macstudio"
opsgate_require_tailscale_context: true
opsgate_allowed_cidrs:
  - "127.0.0.1/32"
  - "::1/128"
  - "100.64.0.0/10"
  - "fd7a:115c:a1e0::/48"

opsgate_ops_ssh_private_key: ""
opsgate_ops_github_ssh_private_key: ""
opsgate_ops_github_ssh_public_key: ""
opsgate_ops_age_private_key: ""
opsgate_ops_github_username: ""
opsgate_ops_github_token: ""
opsgate_ops_manage_workspace_repos: false
opsgate_ops_workspace_repositories:
  - name: "ops-control"
    repo: "git@github.com:ephes/ops-control.git"
    version: "main"
  - name: "ops-library"
    repo: "git@github.com:ephes/ops-library.git"
    version: "main"

opsgate_launchd_manage_state: false
opsgate_api_launchd_manage_state: false
opsgate_runner_launchd_manage_state: false
opsgate_api_launchd_start_service: false
opsgate_runner_launchd_start_service: false
```

Set `opsgate_trust_proxy_headers: true` and `opsgate_session_cookie_secure: true` when the UI is served behind HTTPS ingress.

See `defaults/main.yml` for the full variable reference.

## Example playbook

```yaml
- name: Deploy OpsGate control service and runner (Phase 4B)
  hosts: macstudio
  become: true
  roles:
    - role: local.ops_library.opsgate_deploy
      vars:
        opsgate_source_path: "/Users/jochen/projects/opsgate"
        opsgate_trust_proxy_headers: true
        opsgate_session_cookie_secure: true
        opsgate_ops_manage_workspace_repos: true
        opsgate_launchd_manage_state: true
        opsgate_api_launchd_manage_state: true
        opsgate_runner_launchd_manage_state: true
        opsgate_api_launchd_start_service: true
        opsgate_runner_launchd_start_service: true
```

If GitHub-side access is not ready yet, leave `opsgate_ops_manage_workspace_repos: false` and use the
placeholder directories only until the machine user or deploy-key model is completed.

Recommended key separation:

- `opsgate_ops_ssh_private_key` / `opsgate_ops_ssh_public_key` remain the machine-access keypair for the
  `ops` account
- `opsgate_ops_github_ssh_private_key` / `opsgate_ops_github_ssh_public_key` are the dedicated GitHub
  repo-access keypair installed as `~/.ssh/id_github_ed25519`
- the role renders `~/.ssh/config` so `git@github.com:*` uses the dedicated GitHub key automatically
