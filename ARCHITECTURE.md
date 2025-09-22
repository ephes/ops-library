# Architecture Overview

## Purpose
`ops-library` packages homelab automation that can safely live in a public repository. It provides reusable Ansible content (collection namespace `local.ops_library`) for private control repos such as `ops-control`. The collection focuses on three core patterns:
- **Platform building blocks** – bootstrap roles for Python, uv, Ansible, and SOPS.
- **Service deployment roles** – encapsulated deployment logic for self-hosted services (FastDeploy, Nyxmon, etc.), with strict separation between public logic and private secrets.
- **Service registration roles** – patterns for registering services with FastDeploy for remote execution (e.g., apt upgrades).

## High-Level Structure
```
ops-library/
├── roles/                # First-class Ansible roles shipped in the collection
│   ├── *_deploy/         # Service deployment roles (FastDeploy, Nyxmon)
│   ├── *_remove/         # Service removal roles
│   ├── *_register/       # FastDeploy registration roles
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

## Roles

Roles are the primary surface area. They fall into distinct categories:

| Category | Roles | Purpose |
|----------|-------|---------|
| **Bootstrap** | `ansible_install`, `uv_install`, `sops_dependencies` | Prepare controller or target hosts with required tooling |
| **Service Deployment** | `fastdeploy_deploy`, `nyxmon_deploy` | Deploy application services with full lifecycle management |
| **Service Removal** | `fastdeploy_remove`, `nyxmon_remove` | Complete removal of services for testing or migration |
| **Service Registration** | `apt_upgrade_register`, `fastdeploy_register_service` | Register services with FastDeploy for remote execution |
| **Testing** | `test_dummy` | Example service demonstrating deployment patterns |

Each role follows standard Ansible structure (`defaults/`, `tasks/`, `templates/`, `handlers/`, optional `meta/`). Sensitive or environment-specific values are never hard-coded.

## Packaging Model
- `galaxy.yml` defines the collection metadata (namespace `local`, name `ops_library`, dependencies on `community.general` and `ansible.posix`).
- Consumer repos run `just install-local-library` to build (`ansible-galaxy collection build`) and install the tarball into `collections/ansible_collections/local/ops_library`.
- Version bumps happen by editing `galaxy.yml` before publishing or reinstalling the collection.

## Tooling & Tests
- `justfile` offers tasks for building the collection, running role tests, and installing pre-commit hooks.
- `tests/` plus the shell helpers (`test_runner.sh`, `test_service.sh`, etc.) provide smoke and integration coverage for roles and service flows.
- `README_TESTING.md` and `TESTING.md` document expectations for contributors (pytest harness, Molecule-style checks, etc.).

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
