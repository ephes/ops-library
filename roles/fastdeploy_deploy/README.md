# FastDeploy Deploy Role

Deploy the FastDeploy web-based deployment platform with full database, frontend, and service management.

## Description

This role deploys FastDeploy, a web-based platform for managing service deployments. It handles the complete deployment lifecycle including:
- PostgreSQL provisioning via the shared `postgres_install` role and application migrations
- Python environment management with uv
- Frontend application building
- Systemd service configuration
- Traefik reverse proxy integration
- Initial admin user creation
- Service synchronization from filesystem
- Explicit post-deploy rollout of `fastdeploy.service`
- DB-backed post-restart validation against the running FastDeploy process

## Requirements

- Ubuntu/Debian-based target system
- Ability to install PostgreSQL (handled automatically via dependency)
- Node.js 16+ (for frontend build)
- Python 3.14+ (managed via uv; set `fastdeploy_python_version` if needed)
- ansible-core 2.20+
- Required collections:
  - `ansible.posix` (for synchronize module)
  - `community.general` (for PostgreSQL modules)

## Role Variables

### Required Variables

These variables MUST be set when using this role:

```yaml
fastdeploy_source_path: ""         # Local path to FastDeploy source code
fastdeploy_secret_key: ""          # Django secret key (generate with: openssl rand -hex 32)
fastdeploy_initial_password_hash: ""  # BCrypt hash (generate with: python -c "import bcrypt; print(bcrypt.hashpw(b'password', bcrypt.gensalt()).decode())")
fastdeploy_postgres_password: ""   # PostgreSQL password for FastDeploy database
```

### Common Configuration

Frequently modified settings with sensible defaults:

```yaml
# API and WebSocket URLs
fastdeploy_api_url: "https://deploy.example.com"
fastdeploy_websocket_url: "wss://deploy.example.com/deployments/ws"

# Initial admin user
fastdeploy_initial_user: "admin"

# Traefik configuration
fastdeploy_traefik_enabled: true
fastdeploy_traefik_host: "deploy.example.com"

# Application settings
fastdeploy_app_port: 9999
fastdeploy_workers: 4

# Python / uv
fastdeploy_python_version: "3.14"
```

### Advanced Configuration

```yaml
# User and paths
fastdeploy_user: "fastdeploy"
fastdeploy_home: "/home/fastdeploy"
fastdeploy_site_path: "{{ fastdeploy_home }}/site"

# Database configuration
fastdeploy_postgres_database: "fastdeploy"
fastdeploy_postgres_user: "fastdeploy"

# Feature flags
fastdeploy_build_frontend: true
fastdeploy_create_initial_user: true
fastdeploy_sync_services: true

# Rollout controls
fastdeploy_rollout_restart_enabled: true
fastdeploy_rollout_validation_enabled: true
fastdeploy_rollout_validation_user: "{{ fastdeploy_initial_user }}"
```

For a complete list of variables, see `defaults/main.yml`.

### Service token settings

FastDeploy service tokens carry a `jti` and are recorded so they can be revoked. Tokens issued
before that (no `jti`) are rejected unless `LEGACY_SERVICE_TOKENS_ACCEPTED_UNTIL` is set. These
variables are empty by default, and an empty variable is not written to `.env` (FastDeploy then
uses its own default). Invalid values fail the role before `.env` is written or the service is
restarted. They are checked after the `postgres_install` meta dependency has run, like the secret
checks, so PostgreSQL provisioning still happens on a run that is then refused.

```yaml
# ISO 8601 with a UTC offset; quote it. Temporary: clear it after the cutover.
fastdeploy_legacy_service_tokens_accepted_until: "2026-11-01T00:00:00+00:00"
fastdeploy_service_token_max_expire_days: 90   # SERVICE_TOKEN_MAX_EXPIRE_DAYS (FastDeploy default 90)
fastdeploy_service_token_retention_days: 30    # SERVICE_TOKEN_RETENTION_DAYS (FastDeploy default 30)
```

Edit these through the role, not on the host: the role rewrites `.env` on every run.

#### Legacy token cutover

Deploying a FastDeploy with revocable service tokens rejects every older token at once (for example
Echoport's `FASTDEPLOY_SERVICE_TOKEN` and tokens minted by playbooks). Order:

1. The owner picks the end of the grace period. Set
   `fastdeploy_legacy_service_tokens_accepted_until` to it in the deploy playbook.
2. Deploy FastDeploy with this role. Legacy tokens keep working until that time.
3. Re-issue each token in use on the FastDeploy host and replace the stored secret, then roll out
   its consumer and check that it still triggers deployments:

   ```bash
   cd /home/fastdeploy/site
   sudo -u fastdeploy .venv/bin/python commands.py issueservicetoken \
     --service <service> --user <existing user> --days 90 --origin <consumer>
   sudo -u fastdeploy .venv/bin/python commands.py listservicetokens
   ```

   `issueservicetoken` prints only the token on stdout; `--days` is capped by
   `SERVICE_TOKEN_MAX_EXPIRE_DAYS`.
4. Before the grace period ends, set the variable back to `""` and deploy again. Once the variable
   is cleared (or the time has passed), tokens without `jti` get 401.

#### Legacy token users

Temporary bridge, off by default. Remove it after the token rotation.

FastDeploy accepts a service token only while the user named in its `user` claim exists. That also
holds for tokens without `jti` inside the grace period: a legacy token whose `user` is not a
FastDeploy user gets 401 even though `LEGACY_SERVICE_TOKENS_ACCEPTED_UNTIL` has not passed. List
such names to have the role create them:

```yaml
fastdeploy_legacy_token_users:
  - credential-rotation
```

For each name the role runs FastDeploy's own `commands.py createuser` on the host, with the hash of
a random password that is generated there, never stored and never printed. A name that already
exists is left alone (its password is not changed), so repeated runs report no change.

What such a user is:

- FastDeploy has no roles and no "service account" flag. The user is an ordinary FastDeploy user,
  equal to the initial admin user in what it may do through the API.
- Nobody knows its password, so `/token` login does not work for it. A user token for it can only
  be minted with `SECRET_KEY`, which already allows minting one for any user.
- The legacy tokens get back exactly what they had before FastDeploy started checking the user:
  deployments of the one service named in the token. The `user` claim is otherwise only recorded
  with the deployment.
- New on the host: `commands.py issueservicetoken --user <name>` now works for the name.

Removal, once every consumer uses a re-issued token (step 3 above) under a real user:

1. Set `fastdeploy_legacy_token_users` back to `[]`. The role stops ensuring the users; it does not
   delete them.
2. Delete the users from FastDeploy's `user` table. FastDeploy has no command for that yet. Until
   they are deleted they stay ordinary users without a usable password, and deleting one
   invalidates every service token issued for that name.

### Rollout behavior

Every successful role run is treated as a rollout of the live FastDeploy service:

- the role explicitly restarts `fastdeploy.service` near the end of the deploy flow
- it does not rely on incidental handler notifications from unit-file changes
- after the restart, it validates the running process with an authenticated localhost request to
  `/users/me`

The token for that request is a short-lived user access token, minted on the host by FastDeploy's
own `deploy.auth` function for those (`files/mint_validation_token.py`), run with the application's
interpreter. It is signed with the `SECRET_KEY` and algorithm from the
`.env` the role just wrote; the secret key is not passed on a command line and the role does not
import a JWT library itself. If minting fails, the role reports the exit code and the last line of
the error output.

That validation is DB-backed and secret-backed in the running service process:

- FastDeploy must accept a JWT signed with the configured `SECRET_KEY`
- FastDeploy must successfully load the referenced user from the database

This catches the stale-process class of failures where code, config, or rotated DB credentials were
updated on disk but the long-running FastDeploy process did not pick them up.

If you disable initial-user creation or want validation to target a different existing account, set
`fastdeploy_rollout_validation_user` accordingly.

### PostgreSQL Provisioning

The role automatically pulls in `local.ops_library.postgres_install` to install and configure PostgreSQL. Customize the forwarded settings via:

```yaml
fastdeploy_postgres_version: "17"
fastdeploy_postgres_packages:
  - "postgresql-{{ fastdeploy_postgres_version }}"
  - "postgresql-client-{{ fastdeploy_postgres_version }}"
  - "postgresql-contrib-{{ fastdeploy_postgres_version }}"
  - libpq-dev
fastdeploy_postgres_repo_enabled: true
fastdeploy_postgres_repo_url: https://apt.postgresql.org/pub/repos/apt
fastdeploy_postgres_repo_codename: "{{ ansible_distribution_release | default('jammy') }}"
fastdeploy_postgres_repo_components:
  - main
fastdeploy_postgres_repo_keyring: /etc/apt/keyrings/postgresql.asc
fastdeploy_postgres_repo_key_url: https://www.postgresql.org/media/keys/ACCC4CF8.asc
```

The dependency ensures the `fastdeploy_postgres_database` and `fastdeploy_postgres_user` are created before the application runs migrations.

### Runtime output hardening

The role keeps the normal `syncservices` progress visible, but it intentionally censors the
`Create initial admin user` task in Ansible output. The upstream `commands.py createuser` flow can
emit password-hash and database-error context on failure or duplicate-user runs, so the role runs it
via `command` + environment variables and hides the task result to avoid leaking those values during
FastDeploy-triggered self-deployments.

### Traefik Dual Router Authentication

The role implements a dual router pattern for security:

- **Internal router** (priority 120): LAN and Tailscale clients bypass basic auth
  - IP ranges: RFC1918 private networks, Tailscale CGNAT (100.64.0.0/10), Tailscale IPv6 (fd7a::/48)
- **External router** (priority 100): Public internet requires basic auth
  - Uses shared credentials from `secrets/prod/traefik.yml`

This is **mandatory** for public-facing deployments per security policy.

**Configuration:**

```yaml
fastdeploy_basic_auth_enabled: true  # Default: true
fastdeploy_basic_auth_user: "admin"
fastdeploy_basic_auth_password: "{{ traefik_secrets.basic_auth_password }}"  # Plain text, will be hashed
fastdeploy_internal_ip_ranges:  # Customize for your network
  - "192.168.0.0/16"
  - "100.64.0.0/10"
  - "YOUR_IPV6_PREFIX::/64"
```

**Note:** The role expects a plain-text password in `fastdeploy_basic_auth_password`. It will automatically generate the bcrypt hash using `htpasswd` during deployment. Do NOT provide a pre-hashed password.

**Testing:**
- From LAN (192.168.x): No auth prompt
- From Tailscale (100.x): No auth prompt
- From public internet: Basic auth prompt appears

## Dependencies

This role automatically depends on `local.ops_library.postgres_install` to install PostgreSQL and provision the FastDeploy database/user.

## Contributor Notes

The deploy helper extraction keeps the public role entrypoint unchanged while
moving the duplicated systemd and Traefik plumbing into the internal helper
role `local.ops_library.webapp_deploy_internal`. FastDeploy still owns its
role-specific validation, environment setup, templates, and
application initialization flow. The remaining `user.yml`, `source_*`, and
`python.yml` steps are intentionally still local to this role because the
comparison with `nyxmon_deploy` did not show a narrower stable primitive yet.

## Example Playbook

### Basic Usage

```yaml
- name: Deploy FastDeploy
  hosts: production
  become: true
  vars:
    secrets: "{{ lookup('community.sops.sops', 'secrets/prod/fastdeploy.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.fastdeploy_deploy
      vars:
        fastdeploy_source_path: "/Users/john/projects/fastdeploy"
        fastdeploy_secret_key: "{{ secrets.django_secret_key }}"
        fastdeploy_initial_password_hash: "{{ secrets.admin_password_hash }}"
        fastdeploy_postgres_password: "{{ secrets.db_password }}"
```

### Advanced Usage with Custom Configuration

```yaml
- name: Deploy FastDeploy with Custom Settings
  hosts: production
  become: true
  vars:
    sops_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/fastdeploy.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.fastdeploy_deploy
      vars:
        # Required secrets
        fastdeploy_source_path: "/Users/john/projects/fastdeploy"
        fastdeploy_secret_key: "{{ sops_secrets.django_secret_key }}"
        fastdeploy_initial_password_hash: "{{ sops_secrets.admin_password_hash }}"
        fastdeploy_postgres_password: "{{ sops_secrets.db_password }}"

        # Custom configuration
        fastdeploy_app_port: 10000
        fastdeploy_workers: 8
        fastdeploy_api_url: "https://deploy.internal.example.com"
        fastdeploy_websocket_url: "wss://deploy.internal.example.com/deployments/ws"
        fastdeploy_traefik_host: "deploy.internal.example.com"
        fastdeploy_traefik_cert_resolver: "internal-ca"
```

## Deployment Execution Architecture

When FastDeploy triggers a service, the following execution chain occurs:

```
FastDeploy Service (runs as: fastdeploy)
    │
    └── sudo -u deploy <deploy_script> --config <file>
            (via the service's own /etc/sudoers.d/<service> rule)
            │
            └── optional second step to root, only for the exact script:
                deploy ALL=(root) NOPASSWD:NOSETENV: <service>/backup.py *
```

### Key Components

1. **fastdeploy user**: Runs the FastDeploy web service
2. **deploy user**: Runs the service scripts; it has no general root rights
3. **Sudoers rules**: each registered service (for example through
   `echoport_backup` or the ops-control `register-*-backup.yml` playbooks)
   installs rules that name its own script. This role installs no sudoers
   rule and removes the retired wildcard file `/etc/sudoers.d/fastdeploy`
   (`fastdeploy ALL=(deploy) NOPASSWD: <services>/*/deploy.sh *`), which let
   fastdeploy run any script it wrote into its own services directory.

### For Remote Targets

Runners that reach other hosts (the Echoport production and staging
backups) use the deploy user's key in `/home/deploy/.ssh/`. On production
and staging that key is pinned to the `echoport_remote_command_guard`
allowlist (`from=` macmini's tailnet address, forced command).

### Troubleshooting

If a service run fails, check:
1. **Sudoers**: `sudo -l -U fastdeploy` and `sudo -l -U deploy`
2. **SSH keys**: `ls -la /home/deploy/.ssh/`
3. **Remote allowlist**: refused commands are logged by
   `echoport-remote-command-guard` in the target host's auth log

## Handlers

This role provides no handlers. Traefik watches `/etc/traefik/dynamic` and
loads a changed FastDeploy config without a restart.

## Tags

Available tags for selective execution:

- `fastdeploy_frontend` - Frontend build tasks
- `fastdeploy_service` - Systemd service configuration
- `fastdeploy_traefik` - Traefik reverse proxy configuration

## Testing

```bash
# Run role tests
cd /path/to/ops-library
just test-role fastdeploy_deploy
```

## Changelog

- **1.0.0** (2024-09-22): Initial release with rsync deployment support
- See [CHANGELOG.md](https://github.com/ephes/ops-library/blob/main/CHANGELOG.md) for full history

## License

MIT

## Author Information

Created for homelab automation - part of the ops-library collection.

The application `.env` is owned by `fastdeploy_user:fastdeploy_group` with mode
`0600`. systemd reads it via `EnvironmentFile`; application helpers run as
`fastdeploy_user`, so the deploy user does not need group access to this file.

### Proxy headers and login throttling

Uvicorn explicitly enables proxy headers and trusts only
`fastdeploy_forwarded_allow_ips` (default `["127.0.0.1"]`). Supply a non-empty
list of literal IPv4/IPv6 addresses for trusted proxies; wildcard, CIDR, host
names and command arguments are rejected. Trusted proxy attribution gives the
login failure throttle separate client buckets (50 failures per 15 minutes).
For a remote Traefik instance, set its address, for example `["192.168.1.2"]`.
Only trust proxies that overwrite client-supplied forwarded headers.

This setting applies to `fastdeploy_deploy` units. The separate
`fastdeploy_self_deploy` blue/green role still uses Uvicorn's implicit proxy
trust defaults; a self-deploy replaces the main unit and does not preserve
custom `fastdeploy_forwarded_allow_ips`. Use `fastdeploy_deploy` for this
proxy trust configuration until that role gains matching support.

## Task credential handling

Management commands source a rendered 0600 shell environment companion inside the remote shell, keeping credentials out of command arguments and task environment values. The companion uses the same template as the application env file, with shell quoting enabled only for the companion; the existing application/systemd env format is preserved. Command change reporting and check-mode skips are preserved.
