# static_site_git_refresh

Keep a single-file static site current from a private git repository. A
systemd timer on the target fetches one branch with a read-only deploy key,
rebuilds when the commit changed, validates the one output file, and
atomically replaces the live copy in a document root. Pair it with
[`static_site_deploy`](../static_site_deploy/README.md) in
`static_site_content_source: external` mode, which serves and routes that
document root.

The role is meant for small generated pages such as a private dashboard
rendered from a private repository. It does not push, accept webhooks, or
publish more than one file.

## Requirements

- A Debian 12/13 or Ubuntu target with systemd, `git`, `ssh-keygen`, `flock`,
  `realpath`, `timeout`, and `stat` (coreutils/util-linux).
- The build executable named by the first element of
  `static_site_git_refresh_build_command` already installed (for example
  `/usr/local/bin/uv` from `local.ops_library.uv_install`).
- Outbound SSH to the git host and whatever network the build needs (for a
  `uv run` build: PyPI and, if the project pins a Python uv must download,
  the uv Python mirror).

## Deploy key flow

The role generates an ed25519 key pair on the target in the refresh user's
home. The private key never leaves the target and is not stored in any
inventory or secrets file. Before installing the refresh script, the role
probes read access with `git ls-remote`. If the key cannot read the branch,
the deployment stops and prints the **public** key with these steps:

1. Open the repository's *Settings > Deploy keys > Add deploy key*.
2. Paste the printed public key, leave *Allow write access* unchecked.
3. Re-run the deployment.

The git host key is pinned (`static_site_git_refresh_known_hosts`, GitHub's
published ed25519 key by default) and SSH runs with
`StrictHostKeyChecking=yes`, so there is no trust-on-first-use.

To rotate the key, delete it on the target
(`<home>/.ssh/deploy_key` and `.pub`), remove the old deploy key from the
repository, re-run the deployment, and add the newly printed key.

## Example

```yaml
- name: Serve a private dashboard from git
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.static_site_git_refresh
      vars:
        static_site_git_refresh_name: work-dashboard-refresh
        static_site_git_refresh_repo: git@github.com:owner/private-dashboard.git
        static_site_git_refresh_build_command:
          - /usr/local/bin/uv
          - run
          - python
          - dashboard/build.py
        static_site_git_refresh_output_path: dashboard/dist/index.html
        static_site_git_refresh_publish_path: /srv/work-dashboard/site
        static_site_git_refresh_publish_group: work-dashboard
    - role: local.ops_library.static_site_deploy
      vars:
        static_site_service_name: work-dashboard
        static_site_content_source: external
        static_site_path: /srv/work-dashboard/site
        static_site_path_owner: work-dashboard-refresh
        static_site_path_mode: "2750"
        static_site_host: work.example.internal
        static_site_port: 10064
        static_site_allowed_networks:
          - 100.64.0.0/10
          - fd7a:115c:a1e0::/48
```

Run this role before `static_site_deploy` so the document root holds a page
before the serving role verifies it. Use the same document root, owner, and
group in both roles.

## Refresh behavior

- `<name>.timer` starts the refresh one minute after activation, two minutes
  after boot, and then `static_site_git_refresh_interval` after each run ends.
- Each run takes a non-blocking `flock`; an overlapping run exits cleanly.
- The checkout's `origin` is reset to `static_site_git_refresh_repo` when it
  differs, so a changed repository URL takes effect on the next run.
- The checkout is reset to `origin/<branch>` (`checkout --force --detach`,
  `clean -ffdx` keeping `/.venv`), so local edits on the target never survive.
- A build runs only when the fetched commit differs from the last published
  one or the published file is missing. To rebuild the same commit, delete
  `<home>/published-rev` and start the service.
- The output must be a regular, non-symlink file that resolves inside the
  checkout, be 1 to `static_site_git_refresh_output_max_bytes` bytes, and
  contain `static_site_git_refresh_output_marker` when set. Only then is it
  copied to a temporary file in the document root (mode 0640, service group
  via the setgid directory) and renamed over the live file.
- A failed fetch, build, or validation fails the systemd unit and leaves the
  last good page live.
- Deployment runs one refresh synchronously when
  `static_site_git_refresh_run_on_deploy` is true and forces a rebuild when the
  refresh script or service unit changed.

The service runs as the dedicated refresh user with `ProtectSystem=strict`,
`ProtectHome=true`, `NoNewPrivileges=true`, and write access limited to its
home and the document root.

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `static_site_git_refresh_name` | `static-site-refresh` | Account, script, and unit prefix. |
| `static_site_git_refresh_user` / `_group` | name | Dedicated system account. |
| `static_site_git_refresh_home` | `/var/lib/<name>` | State directory: checkout, deploy key, lock, published revision. Must not be under `/home` or `/root`. |
| `static_site_git_refresh_repo` | `""` | Required SSH clone URL. |
| `static_site_git_refresh_branch` | `main` | Branch to follow. |
| `static_site_git_refresh_checkout_path` | `<home>/checkout` | Working checkout. |
| `static_site_git_refresh_deploy_key_path` | `<home>/.ssh/deploy_key` | Generated private key. |
| `static_site_git_refresh_known_hosts` | GitHub ed25519 key | Pinned host key lines. |
| `static_site_git_refresh_build_command` | `[]` | Required argv; first element is an absolute executable path. |
| `static_site_git_refresh_build_environment` | `{}` | Extra environment for the build. |
| `static_site_git_refresh_build_timeout_seconds` | `600` | Build time limit. |
| `static_site_git_refresh_output_path` | `dist/index.html` | Built file relative to the checkout. |
| `static_site_git_refresh_output_max_bytes` | `20971520` | Upper size bound. |
| `static_site_git_refresh_output_marker` | `""` | Optional required text. |
| `static_site_git_refresh_publish_path` | `""` | Required document root. |
| `static_site_git_refresh_publish_group` | `""` | Required group that serves the document root. |
| `static_site_git_refresh_publish_name` | `index.html` | Published file name. |
| `static_site_git_refresh_interval` | `5min` | systemd time span between runs. |
| `static_site_git_refresh_run_on_deploy` | `true` | Run one refresh during deployment. |

## Operations

```bash
systemctl list-timers '<name>.timer'
journalctl -u <name>.service -n 50 --no-pager
sudo systemctl start <name>.service           # refresh now
cat /var/lib/<name>/published-rev             # commit currently live
```

## Removal

Stop and disable `<name>.timer`, stop `<name>.service` (a run may be in
progress), delete `<name>.service`, `<name>.timer`,
the refresh script, and the state directory, then remove the deploy key from
the repository. The document root belongs to the serving role.
