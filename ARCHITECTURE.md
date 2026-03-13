# Architecture Overview

## Purpose
`ops-library` packages homelab automation that can safely live in a public repository. It provides reusable Ansible content (collection namespace `local.ops_library`) for private control repos such as `ops-control`. The collection focuses on three core patterns:
- **Platform building blocks** – bootstrap roles for Python, uv, Ansible, and SOPS.
- **Service deployment roles** – encapsulated deployment logic for self-hosted services (FastDeploy, Nyxmon, etc.), with strict separation between public logic and private secrets.
- **Service registration/orchestration roles** – patterns for registering services with FastDeploy or Echoport for remote execution.

## High-Level Structure
```
ops-library/
├── roles/                # First-class Ansible roles shipped in the collection
│   ├── *_deploy/         # Service deployment roles (FastDeploy, Nyxmon)
│   ├── *_backup/         # Dedicated backup roles when a service still keeps one
│   ├── *_restore/        # Dedicated restore roles when a service still keeps one
│   ├── *_remove/         # Service removal roles
│   ├── *_register/       # FastDeploy registration roles
│   ├── *_shared/         # Shared-defaults surfaces for sibling lifecycle roles
│   ├── *_internal/       # Internal helper roles
│   └── *_install/        # Platform bootstrap roles
├── docs/, examples/      # Human documentation and sample usage
├── tests/, test_runner   # Focused integration tests for roles
├── justfile              # Developer helpers (build/install collection, run tests)
├── galaxy.yml            # Collection metadata (namespace, version, dependencies)
└── pyproject.toml        # Tooling configuration (linting, formatting, type checks)
```

## Design Principles

1. **Separation of Concerns**: Public deployment logic in ops-library, private secrets in consumer repositories
2. **Secret Validation**: Secrets must be supplied by consumers and are validated at runtime—placeholder values such as "CHANGEME" are explicitly rejected
3. **Idempotency**: All roles must be safely runnable multiple times without unintended side effects
4. **Deployment Methods**: Support both `rsync` (development) and `git` (production) deployment patterns
5. **Fail-Fast Validation**: Roles validate all required variables and secrets before execution using assert tasks

## Role Taxonomy

Roles are the primary surface area, but they no longer form one flat category.

| Surface | Examples | Contract |
|----------|----------|----------|
| **Public lifecycle entrypoints** | `fastdeploy_deploy`, `unifi_restore`, `tailscale_backup`, `apt_upgrade_register`, `uv_install` | Stable role names that consumer repos are expected to call directly. |
| **Shared-defaults roles** | `homelab_shared`, `jellyfin_shared`, `mail_shared`, `postfixadmin_shared`, `vaultwarden_shared` | Shared variable and fact surfaces for sibling lifecycle roles. Usually loaded by `meta/main.yml` dependencies rather than by operators. |
| **Internal helpers** | `webapp_deploy_internal`, `restore_pilot_internal`, `minio_shared` | Narrow implementation details for other roles. Not part of the public compatibility contract. |

Each role still follows standard Ansible structure (`defaults/`, `tasks/`,
`templates/`, `handlers/`, optional `meta/`). Sensitive or environment-specific
values are never hard-coded.

### Shared-Defaults Roles

Most retained `*_shared` roles are real shared-defaults surfaces:

- `homelab_shared`
- `jellyfin_shared`
- `mail_shared`
- `mastodon_shared`
- `metube_shared`
- `navidrome_shared`
- `postfixadmin_shared`
- `snappymail_shared`
- `tailscale_shared`
- `takahe_shared`
- `vaultwarden_shared`

Repo-specific nuances matter here:

- `mail_shared` is a documented defaults surface, but its sibling mail roles do
  not currently auto-include it through `meta/main.yml`. Those roles still own
  their role-local defaults with `mail_backend_*`, `mail_relay_*`,
  `mail_backup_*`, and `mail_restore_*` prefixes.
- `vaultwarden_shared` is intentionally partial. `vaultwarden_backup` and
  `vaultwarden_restore` depend on it today; `vaultwarden_deploy` and
  `vaultwarden_remove` keep their own role-local defaults.
- `homelab_shared` also exports the `homelab_paths` fact for sibling lifecycle
  roles.

Shared-defaults roles should stay small and explicit. They exist to centralize
stable variables/facts for sibling roles, not to hide major orchestration.

### Internal Helper Surfaces

When multiple public roles share a small, stable implementation detail,
`ops-library` may add an internal helper role or task library while keeping the
public entrypoint unchanged.

Current helper surfaces:

- `webapp_deploy_internal` centralizes the narrow single-unit systemd and
  Traefik rendering steps shared by the landed web-application deploy helper
  extraction.
- `restore_pilot_internal` centralizes the narrow restore pilot scaffold shared
  by `fastdeploy_restore` and `unifi_restore`: host-local archive/snapshot
  validation plus the `block`/`rescue`/`always` orchestration that still calls
  back into role-owned `validate`, `prepare`, `restore`, `verify`, `rollback`,
  and `cleanup` task files.
- `minio_shared` is an internal helper task library, not a shared-defaults
  role. It currently exposes `tasks/mc_host_env.yml` for MinIO backup/restore
  flows that need consistent `MC_HOST_*` environment construction.

Internal helpers are not the public compatibility contract. Keep them small,
document them at the role level, and prefer preserving existing public role
names and behavior over expanding helper abstraction.

## Packaging Model
- `galaxy.yml` defines the collection metadata (namespace `local`, name `ops_library`, dependencies on `community.general` and `ansible.posix`).
- Consumer repos run `just install-local-library` to build (`ansible-galaxy collection build`) and install the tarball into `collections/ansible_collections/local/ops_library`.
- Version bumps happen by editing `galaxy.yml` before publishing or reinstalling the collection.

## Tooling & Tests
- `justfile` offers tasks for building the collection, running role tests, and installing pre-commit hooks.
- `tests/` plus the shell helpers (`test_runner.sh`, `test_service.sh`, etc.) provide smoke and integration coverage for roles and service flows.
- `README_TESTING.md` and `TESTING.md` document expectations for contributors (pytest harness, Molecule-style checks, etc.).
- {doc}`Service Lifecycle Guide <howto/service_lifecycle>` captures the checklist for adding or refactoring lifecycle roles and should stay aligned with these architecture notes.

## Echoport And Role Dispositions

Echoport is now the primary backup/restore orchestrator for many services in the
collection. That means dedicated `*_backup` and `*_restore` roles are no longer
one uniform category.

Current public disposition terms:

- `primary`: the dedicated role family is still the main public operator path
- `exception`: explicitly outside the default Echoport migration path
- `ad-hoc only`: keep callable for break-glass or manual use, but not the
  preferred operator workflow
- `deprecated`: retained for compatibility while Echoport is the preferred path

Important current examples:

- `mail_*` and `minio_*` are explicit exceptions.
- `archive` and `openclaw` are Echoport-first services with no dedicated public
  `*_backup` / `*_restore` roles.
- Some families split by action: for example `fastdeploy_backup` is deprecated
  while `fastdeploy_restore` remains ad-hoc only, and the same pattern applies
  to `unifi_*` and `homelab_*`.
- `vaultwarden_*`, `homeassistant_*`, `nyxmon_*`, and `paperless_*` dedicated
  backup/restore roles are deprecated in this model.

Top-level docs and role READMEs should say which path is primary instead of
implicitly treating the older controller-local `~/backups/...` model as the
default for every service.

## Restore Scaffold Boundary

The restore pilot boundary remains intentionally narrow even after the pilot
validation work. `restore_pilot_internal` only covers the repo-proven host-local
scaffold used by:

- `fastdeploy_restore`
- `unifi_restore`

These two roles share the same repo-proven shape:

- host-local archive resolution under a remote backup root
- split restore phases (`validate`, `restore`, `verify`, `cleanup`) plus one preparatory safety phase (`safety_backup` or `prepare`)
- `block`-based orchestration with an explicit rollback path
- metadata and manifest validation before destructive steps
- post-restore health checks that stay on the target host

This boundary is about present structure, not idealized abstraction.
`restore_pilot_internal` is intentionally limited to the two proven host-local
pilots. It is not a generic restore framework for delayed roles.

When the helper resolves `latest` archives, exclusion regexes are treated as
soft preferences. If every discovered archive matches the exclusion list, the
helper falls back to the unfiltered archive list instead of failing outright.

### Delayed Restore Roles

The following restore roles remain outside that scaffold on purpose:

- `homeassistant_restore`: scaffolded, but uses controller-fallback transport and has no rescue/rollback block in `main.yml`
- `paperless_restore`: scaffolded, but uses controller-fallback transport and has the heaviest validation path in this family
- `vaultwarden_restore`: monolithic and controller-local by design
- `minio_restore`: extended multi-phase exception for object-storage recovery
- `nyxmon_restore`: incomplete scaffold; no rollback phase and its `local_cache` story is still unfinished
- `minecraft_java_restore`: hybrid multi-file restore split (`resolve_archive`, `stop_service`, `restore_data`, `start_service`), but not the pilot scaffold pattern
- `mail_restore`, `postfixadmin_restore`, `snappymail_restore`: mail-adjacent narrow restores with their own established flows

The current architecture documents these roles rather than folding them into
the restore pilot helper. Their differences are meaningful enough that
treating them as pilot inputs now would make the first shared extraction less
safe, not more representative.

### Restore Validation Harness

The restore pilot boundary now has executable Molecule coverage at the role level:

- `fastdeploy_restore`: archive resolution, validation-only dry run, post-restore health checks, and targeted rollback replay using a seeded safety snapshot
- `unifi_restore`: archive resolution, post-restore health checks, and targeted rollback replay using a seeded safety snapshot

The harness is intentionally role-local. It proves the landed pilot boundary,
but it does not imply that delayed restore roles already fit the same
scaffold.

## FastDeploy Service Registry Pattern

FastDeploy provides an API-driven interface for privileged operations, allowing unprivileged services to trigger maintenance tasks without requiring direct SSH root access. Services only need a FastDeploy API token to execute pre-registered operations like system updates, backups, or database maintenance.

### Example: System Update Registration

1. **Registration Phase** (one-time setup):
   ```yaml
   # Consumer playbook registering apt upgrades for staging
   - name: Register system updates with FastDeploy
     hosts: deployment_server
     vars:
       ssh_keys: "{{ encrypted_secrets }}"
     roles:
       - role: local.ops_library.apt_upgrade_register
         vars:
           apt_upgrade_target: "staging.example.com"
           apt_upgrade_ssh_private_key: "{{ ssh_keys.private_key }}"
   ```

2. **Role Creates** (in `/home/fastdeploy/site/services/apt_upgrade_staging/`):
   - `config.json`: Service metadata for FastDeploy UI
   - `deploy.py`: Python script that executes ansible and reports progress
   - `deploy.sh`: Shell wrapper for FastDeploy to invoke
   - `playbook.yml`: Ansible playbook that runs the actual apt upgrade
   - SSH keys deployed to `/home/deploy/.ssh/` for remote access

3. **Execution Phase** (triggered via API or UI):
   - Unprivileged service sends API request with FastDeploy token
   - FastDeploy validates token and permissions
   - Executes registered operation with proper privileges
   - Returns real-time progress updates via JSON

### Use Cases for Registration Pattern

- **System Maintenance**: apt updates, package upgrades, security patches
- **Backup Operations**: Database dumps, file backups, snapshot creation
- **Database Tasks**: Migrations, vacuum operations, restore procedures
- **Certificate Renewal**: Let's Encrypt updates, key rotation
- **Log Rotation**: Cleanup, archival, compression

### Key Features of Registration Roles

- **API Access Control**: Operations exposed via REST API with token authentication
- **Privilege Separation**: Unprivileged services can trigger privileged operations safely
- **SSH Key Management**: Deploy persistent SSH keys from encrypted secrets
- **Sudoers Configuration**: Fine-grained permission control for operations
- **Progress Reporting**: Real-time JSON-formatted status updates
- **Audit Trail**: All operations logged with user, timestamp, and outcome

## Integration with Consumer Repositories

Consumer repositories reference the collection as `local.ops_library.<role_name>`. The contract between this collection and consumers is:

1. **ops-library provides**: Declarative automation logic with safe defaults, never containing secrets or environment-specific configuration
2. **Consumers provide**: Inventories, encrypted secrets, and thin orchestration playbooks that supply environment-specific variables
3. **Collection updates**: Consumers rebuild/reinstall the collection locally to access new features

This separation ensures:
- Reusable logic remains public and testable
- Sensitive data stays in private repositories
- Clear boundaries between automation logic and configuration
- Easy updates through standard Ansible collection mechanisms
