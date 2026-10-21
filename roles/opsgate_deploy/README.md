# opsgate_deploy

Deploy OpsGate on macOS (`launchd` host model) with the Phase 4B control service + runner baseline.

## What this role does

- Creates and manages both required users:
  - `control_service_user` for API/UI process execution
  - `ops` for runner/tmux execution
- Grants `control_service_user` read access to the `ops` artifact tree so the web UI can display runner logs
- Creates spec-aligned execution layout:
  - `ops_home_dir` (default `/Users/ops`)
  - `execution_data_dir` (default `{{ ops_home_dir }}/remediation`)
  - `tickets_dir` (default `{{ execution_data_dir }}/jobs`)
  - `session_artifacts_dir` (default `{{ execution_data_dir }}/sessions`)
- Syncs local app source (`opsgate_source_path`) into:
  - `{{ opsgate_app_dir }}` (API/UI runtime, `control_service_user`)
  - `{{ opsgate_runner_app_dir }}` (runner runtime, `ops`)
  - `opsgate_rsync_excludes` keeps VCS metadata, virtualenvs, caches and the
    top-level Rust port workspace `rust/` (sources and `cargo build` output in
    `rust/target/`) out of both app directories. `rsync --delete` never
    removes excluded paths on the target, so a `rust/` synced by an older role
    version stays in the app directories; it is inert (the Python runtime
    never reads it) and can be removed by hand.
- Installs runtime dependencies using `uv sync --frozen --no-dev` for both runtimes
- Wires optional `ops` credentials (machine SSH key, per-repository GitHub deploy keys or a dedicated GitHub account SSH key, SOPS age key, GitHub token)
- Optionally clones/updates managed `ops` workspaces (for example `ops-control`, `ops-library`) once GitHub-side access exists
- Renders API/runner env files under `/etc/opsgate`
- Writes tmux defaults for the `ops` runner account
- Renders two LaunchDaemons:
  - `de.wersdoerfer.opsgate.api` as `control_service_user`
  - `de.wersdoerfer.opsgate.runner` as `ops`
- Runs each unit as Python (the venv, default) or as the pinned Rust release
  binary, installs and validates that release, verifies the running units and
  prunes old releases (see [Implementation: Python or Rust](#implementation-python-or-rust))
- Leaves HTTPS ingress to a separate Traefik-facing role on the edge host

## Important defaults

- `opsgate_launchd_manage_state: false`
- `opsgate_launchd_start_services: false`
- `opsgate_api_launchd_manage_state: "{{ opsgate_launchd_manage_state }}"`
- `opsgate_runner_launchd_manage_state: "{{ opsgate_launchd_manage_state }}"`
- `opsgate_api_launchd_start_service: "{{ opsgate_launchd_start_services }}"`
- `opsgate_runner_launchd_start_service: "{{ opsgate_launchd_start_services }}"`

## Implementation: Python or Rust

OpsGate is being ported to one Rust binary `opsgate` (`rust/` in the opsgate
repository, plan section 10.1; releases `rs-v<version>` on
`github.com/ephes/opsgate`). Each launchd unit has its own switch:

```yaml
opsgate_api_impl: python          # python | rust
opsgate_runner_impl: python       # python | rust
opsgate_rust_version: ""          # e.g. "0.3.0"; required when any impl is rust
opsgate_rust_sha256: ""           # sha256 of the release archive
opsgate_rust_release_url: >-      # default: the GitHub release asset
  https://github.com/ephes/opsgate/releases/download/rs-v{{ opsgate_rust_version }}/opsgate-{{ opsgate_rust_version }}-aarch64-apple-darwin.tar.gz
opsgate_rust_local_archive: ""    # archive on the controller (development)
opsgate_rust_install_root: /usr/local/libexec/opsgate-rs
opsgate_rust_keep_versions: 3
opsgate_launchd_python_plist_dir: "{{ opsgate_config_dir }}/launchd-python"
opsgate_launchd_verify_retries: 10   # x delay seconds for the live checks
opsgate_launchd_verify_delay: 3
```

Set the four `opsgate_*_impl`/`opsgate_rust_*` values in the host vars, not
as role vars of the playbook (role vars would override the inventory).

What a deploy does (`tasks/rust_binary.yml`, `launchd.yml`, `verify.yml`,
`prune.yml`):

1. **Validation** (`validate.yml`, before anything changes): both impls are
   `python` or `rust`; any `rust` needs `opsgate_rust_version`; a version needs
   a 64-hex `opsgate_rust_sha256` or a local archive; a checksum or local
   archive without a version is refused.
2. **Install** (whenever a version is set, independent of the impls, so a
   release can be installed ahead of a switch): download with `get_url` and
   the pinned checksum (or copy the local archive after checking it), require
   exactly the regular files `opsgate` and `LICENSE` at the archive root,
   unpack into `<root>/<version>/` (`root:wheel`, binary `0755`), record the
   archive checksum in `.archive-sha256`. An installed version directory is
   never modified; a different archive for an installed version fails.
3. **Validation of the candidate by its versioned path**, before any plist
   points at it: `--version` reports `opsgate <version> (<commit>)`;
   `check-config api` as `control_service_user` and `check-config runner` as
   `ops` (`sudo -u <user> env HOME=… PATH=… OPSGATE_ENV_FILE=<env file path>`;
   only the env-file path is passed, never a value from it); `check-db --db
   <opsgate_db_path>` as `control_service_user` (read-only; skipped while the
   database does not exist yet). When a rejected release was installed by this
   run it is removed again. If any unit runs `rust`, the play stops with the
   plists and running units untouched. With both impls `python` the failure is
   reported as an ignored error and the deploy goes on with Python (nothing is
   pruned), so a broken release, or one that rejects a configuration or
   database Python accepts, never blocks the rollback to Python.
4. **Plists**: `python` renders today's `ProgramArguments` (the venv command,
   `opsgate_api_program_arguments` / `opsgate_runner_program_arguments`);
   `rust` renders `/usr/bin/env bash -lc "cd <dir> && exec
   <root>/<version>/opsgate serve"` (`runner` for the runner), where `<dir>` is
   the directory the Python command enters (`opsgate_app_dir`,
   `opsgate_runner_app_dir`), so the login-shell environment and the process
   working directory stay the same. `EnvironmentVariables`, `UserName`,
   `GroupName`, `WorkingDirectory`, logs and labels are the same for both. A
   version change or an impl flip changes only that unit's plist, so only that
   unit is booted out/in and kickstarted. With both impls `python` the plists
   are byte-identical to the ones before the switch existed. The Python source
   sync, `uv sync` and the env files stay for both impls (the rollback path);
   a changed Python source or venv restarts only a unit that runs Python, a
   changed env file restarts the unit either way.
5. **Verification** of each managed and started unit (retrying for up to
   `retries x delay` = 30 s): `launchctl print system/<label>` shows it running
   with a pid; `rust`: `ps -o comm=` of that pid is the versioned binary and its
   arguments are `<binary> serve|runner`; `python`: `ps -o args=` ends in `-m
   opsgate serve|runner` and the executable is not below the install root;
   API: `GET http://127.0.0.1:<opsgate_api_bind_port>/api/v1/health` answers
   `status == "ok"`.
6. **Prune** after the verification: version directories beyond the
   `opsgate_rust_keep_versions` newest are removed, never the pinned version,
   a version a unit's live process runs, or a unit's previous version
   (`<root>/.previous-api`, `<root>/.previous-runner`: written when a unit's
   plist moves away from a Rust version, to another version or to Python).
   Nothing is pruned in check mode, after a rejected release, or when the
   live state of a unit cannot be read completely. Hidden entries, links and
   directories not named like a version are never touched.

### Rollback

- **Normal, per unit:** set `opsgate_api_impl` or `opsgate_runner_impl` back
  to `python` in the host vars and deploy. The plist returns to the venv
  command and launchd restarts that unit. The database and artifacts are
  shared by both implementations (approvers sign in again after an API
  switch).
- **Rust to Rust:** pin the previous version and its sha256; its directory is
  still installed (it is the unit's previous version, which prune keeps).
- **Emergency on the host (root, without Ansible):** every deploy renders the
  Python variant of each plist to
  `/etc/opsgate/launchd-python/<label>.plist` (`root:wheel 0644`, never
  loaded):

  ```bash
  launchctl bootout system/<label>
  cp /etc/opsgate/launchd-python/<label>.plist /Library/LaunchDaemons/
  launchctl bootstrap system /Library/LaunchDaemons/<label>.plist
  ```

  Then set the unit's impl to `python` in the inventory before the next
  deploy: a deploy with `rust` reinstates the Rust plist.

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

### Per-repository deploy keys

`opsgate_ops_github_deploy_keys` maps the `name` of a GitHub SSH entry in
`opsgate_ops_workspace_repositories` to its own key pair (`private_key`,
`public_key`), typically a read-only GitHub deploy key of that repository
(a deploy key works for one repository only). For each entry the role:

- installs the pair as `~/.ssh/id_github_deploy_<name>` (`0600`) and
  `~/.ssh/id_github_deploy_<name>.pub`
  (`opsgate_ops_github_deploy_key_path_prefix`);
- renders a `Host github-<name>` block into `~/.ssh/config` (`HostName
  github.com`, `HostKeyAlias github.com`, `IdentitiesOnly yes`);
- clones and fetches the repository as `git@github-<name>:<owner>/<repo>.git`.
  The git module also rewrites `origin` of an existing clone to that URL, so a
  plain `git fetch` in the workspace uses the same key.

When deploy keys are configured and `opsgate_ops_github_ssh_private_key` is
empty, the role removes the old account key files
(`opsgate_ops_github_ssh_private_key_path` and its `.pub`) and no longer renders
the `Host github.com` block. Validation requires each deploy-key name to match
exactly one GitHub SSH workspace repository, and every GitHub SSH workspace
repository to have either a deploy key or the account key.

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
opsgate_ops_github_deploy_keys: {}
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
- preferred over the account key: `opsgate_ops_github_deploy_keys`, one read-only deploy key per repository
  (see [Per-repository deploy keys](#per-repository-deploy-keys))
