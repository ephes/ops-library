# MinIO Deploy Role

Deploys MinIO object storage server as a hardened systemd service with optional TLS and bucket/policy bootstrap.

## Features

- **Version Pinned**: Reproducible deployments with mandatory checksum validation
- **Secure by Default**: Systemd hardening, loopback binding, credential validation
- **Single-Node Ready**: LUKS-encrypted data directory support
- **Optional Bootstrap**: mc client, buckets, versioning, policies, service accounts
- **Idempotent**: Safe to run multiple times
- **Verification Built-in**: Automatic health checks after deployment

## Quick Start

### Minimal Deployment (Internal Only)

```yaml
- hosts: server
  become: true
  vars:
    sops_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/minio.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.minio_deploy
      vars:
        minio_root_user: "{{ sops_secrets.root_user }}"
        minio_root_password: "{{ sops_secrets.root_password }}"
        minio_version: "RELEASE.2024-10-02T17-50-41Z"
        minio_checksum: "sha256:abc123..."
```

### With Bootstrap (Buckets + Service Accounts)

```yaml
- hosts: server
  become: true
  vars:
    sops_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/minio.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.minio_deploy
      vars:
        # Credentials
        minio_root_user: "{{ sops_secrets.root_user }}"
        minio_root_password: "{{ sops_secrets.root_password }}"

        # Version pinning (REQUIRED)
        minio_version: "RELEASE.2024-10-02T17-50-41Z"
        minio_checksum: "sha256:abc123..."

        # Data directory
        minio_data_dirs:
          - /mnt/cryptdata/minio/data

        # Bootstrap
        minio_bootstrap_with_mc: true
        minio_mc_version: "RELEASE.2024-10-02T17-50-41Z"
        minio_mc_checksum: "sha256:def456..."

        minio_buckets:
          - name: backups
            versioning: true
            policy: private

        minio_service_accounts:
          - name: app
            access_key: "{{ sops_secrets.app_access_key }}"
            secret_key: "{{ sops_secrets.app_secret_key }}"
            policy: readonly
            allowed_buckets: [backups]
```

## Architecture

```
┌─────────────────┐
│   Application   │
│   (echoport)    │
└────────┬────────┘
         │ S3 API
         ▼
┌─────────────────┐      ┌──────────────────┐
│ MinIO Service   │◄────►│ Web Console      │
│ 127.0.0.1:9001  │      │ 127.0.0.1:9002   │
└────────┬────────┘      └──────────────────┘
         │
         ▼
┌─────────────────┐
│  LUKS Encrypted │
│  Data Directory │
│  /mnt/cryptdata │
└─────────────────┘
```

## Role Variables

### Required Variables

| Variable | Example | Description |
|----------|---------|-------------|
| `minio_root_user` | `"admin"` | Root username (from SOPS) |
| `minio_root_password` | `"..."` | Root password (from SOPS) |
| `minio_version` | `"RELEASE.2024-10-02T17-50-41Z"` | Explicit MinIO version |
| `minio_checksum` | `"sha256:abc..."` | SHA256 checksum for binary |

### Bootstrap Variables (if `minio_bootstrap_with_mc: true`)

| Variable | Example | Description |
|----------|---------|-------------|
| `minio_mc_version` | `"RELEASE.2024-10-02T17-50-41Z"` | mc client version |
| `minio_mc_checksum` | `"sha256:def..."` | SHA256 checksum for mc |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `minio_bind_host` | `127.0.0.1` | Bind address (loopback by default) |
| `minio_api_port` | `9001` | S3 API port |
| `minio_console_port` | `9002` | Web console port |
| `minio_traefik_host` | `minio.home.example.com` | Console host when exposed via Traefik |
| `minio_traefik_api_host` | `s3.{{ minio_traefik_host }}` | S3 API host when exposed via Traefik |
| `minio_data_dirs` | `[/var/lib/minio/data]` | Data directory paths |
| `minio_tls_enable` | `false` | Enable TLS |
| `minio_bootstrap_with_mc` | `false` | Enable bucket/policy bootstrap |

See `defaults/main.yml` for the complete list.

## Version Pinning & Checksums

The pinned defaults' server and client download URLs returned HTTP 410 during
2026-10-28 research. This affects unchanged Ansible downloads too: a fresh
installation or upgrade cannot fetch those artifacts from those URLs. A
matching installed executable can be reused. The commands below describe the
upstream layout, not evidence of current artifact availability; verify a
reviewed, checksummed source before scheduling a fresh install or upgrade.
No alternative release or artifact source is selected by this documentation.

**SECURITY REQUIREMENT**: Version pinning is mandatory for reproducible and secure deployments.

### Get MinIO Checksums

```bash
# List available release builds
curl -s https://dl.min.io/server/minio/release/linux-amd64/archive/ | grep RELEASE

# List available hotfix builds
curl -s https://dl.min.io/server/minio/hotfixes/linux-amd64/archive/archive/ | grep RELEASE

# Get checksum for a release build
VERSION="RELEASE.2024-10-02T17-50-41Z"
curl -s "https://dl.min.io/server/minio/release/linux-amd64/archive/minio.${VERSION}.sha256sum"

# Get checksum for a hotfix build
HOTFIX_VERSION="RELEASE.2025-10-15T17-29-55Z.hotfix.c392ab039"
curl -s "https://dl.min.io/server/minio/hotfixes/linux-amd64/archive/archive/minio.${HOTFIX_VERSION}.sha256sum"
```

### Get mc Client Checksums

```bash
# Get mc checksum
VERSION="RELEASE.2024-10-02T17-50-41Z"
curl -s "https://dl.min.io/client/mc/release/linux-amd64/archive/mc.${VERSION}.sha256sum"
```

## Backup accounts

`tasks_from: backup_account` creates or updates one MinIO user for one backup
target. It is not part of the deploy: a play on the MinIO host includes it per
target, after the bootstrap has configured the admin alias
(`minio_host_alias`) for root.

```yaml
- name: Create the scoped MinIO account of the delve backup
  ansible.builtin.include_role:
    name: local.ops_library.minio_deploy
    tasks_from: backup_account
  vars:
    minio_backup_account_name: delve
    minio_backup_account_secret_key: "{{ secrets.delve }}"  # 32 to 40 characters
```

| Variable | Default | Description |
|----------|---------|-------------|
| `minio_backup_account_name` | `""` | Target name. The policy is `backup-<name>`. |
| `minio_backup_account_secret_key` | `""` | Secret key, 32 to 40 characters. |
| `minio_backup_account_user` | `bk-` + 17 hex digits of the name's SHA-256 | MinIO user name (3 to 20 characters). An identifier, not a secret. |
| `minio_backup_account_bucket` | `backups` | Bucket the account works in. |
| `minio_backup_account_prefixes` | `[<name>]` | Key prefixes the account may use. |
| `minio_backup_account_allow_delete` | `false` | Also allow `s3:DeleteObject` below the prefixes. |
| `minio_backup_account_allow_put` | `true` | Allow `s3:PutObject`. `false` for an account that only reads and deletes. |
| `minio_backup_account_whole_bucket` | `false` | Grant the object actions and listing on the whole bucket instead of the prefixes. |
| `minio_backup_account_policy_dir` | `/etc/minio/policies` | Where the policy document is kept on the host. |

The policy allows `s3:GetObject` and `s3:PutObject` on
`<bucket>/<prefix>/*`, `s3:ListBucket` on the bucket for keys below the
prefixes, and `s3:GetBucketLocation`. That covers `mc cp` in both directions
(including multipart uploads), `mc stat` and `mc ls` of the own prefix. The
account cannot list or read another prefix or bucket, delete anything, or use
the admin API. It can overwrite its own objects; enable bucket versioning if
that matters.

A retention job that expires archives of every target (Echoport's cleanup)
gets an account of its own with `minio_backup_account_whole_bucket: true`,
`minio_backup_account_allow_delete: true` and
`minio_backup_account_allow_put: false`: it may list the whole bucket, read
(`mc stat`) and delete any object in it, but not write, touch another bucket
or use the admin API.

The tasks are idempotent. The policy is written to the server and
`mc admin user add` runs on every pass, so a failed earlier run, a change made
by hand and a rotated secret are all corrected,
and the run ends by proving that the user is enabled, holds exactly
`backup-<name>` and belongs to no group. The secret is passed to mc on stdin
in a `no_log` task and never appears in a command line.

## Bootstrap Features

### Buckets

```yaml
minio_buckets:
  - name: backups
    versioning: true
    policy: private
  - name: public-data
    versioning: false
    policy: public
```

**Policies**: `private`, `readonly`, `writeonly`, `public`

### Service Accounts

```yaml
minio_service_accounts:
  - name: echoport
    access_key: "{{ sops_secrets.echoport_access_key }}"
    secret_key: "{{ sops_secrets.echoport_secret_key }}"
    policy: readonly
    allowed_buckets:
      - backups
```

## TLS Configuration

To enable TLS, provide certificate content via SOPS:

```yaml
# In SOPS secrets file
tls_cert: |
  -----BEGIN CERTIFICATE-----
  ...
  -----END CERTIFICATE-----
tls_key: |
  -----BEGIN PRIVATE KEY-----
  ...
  -----END PRIVATE KEY-----

# In playbook
minio_tls_enable: true
minio_tls_cert_content: "{{ sops_secrets.tls_cert }}"
minio_tls_key_content: "{{ sops_secrets.tls_key }}"
```

## Verification

The role automatically verifies:
- ✓ API endpoint reachable
- ✓ Console endpoint reachable
- ✓ Health check passes
- ✓ mc alias works (if bootstrap enabled)
- ✓ Buckets exist (if bootstrap enabled)

### Manual Verification

```bash
# On target host
mc alias set local http://127.0.0.1:9001 <ROOT_USER> <ROOT_PASS>
mc admin info local
mc ls local/
```

## Security Considerations

1. **Loopback Binding**: Default binds to 127.0.0.1 (internal only)
2. **Systemd Hardening**: NoNewPrivileges, PrivateTmp, ProtectSystem, etc.
3. **Credential Validation**: Deployment fails with "CHANGEME" placeholders
4. **Checksum Validation**: Binary integrity verified before installation
5. **No Secrets in Logs**: `no_log: true` for sensitive operations

## Native-qualified pyinfra convergence contract

The [published pyinfra contract](https://github.com/ephes/ops-deploy/blob/3c621d1b9edf404e3e6a433d5f77e94d04f6cb06/docs/services/minio.md)
defines its additional identity/policy inputs and limitations. In that API,
`MinioIdentity.exact` requires exactly its declared attachments and no groups;
additive identities permit other attachments. `MinioSupersededPolicy` declares
an obsolete policy to retire. The weeknotes example is a private caller's
immutable versioned policy, not a new Ansible variable.

The separately implemented public pyinfra runtime is native-qualified; private
inventory adoption remains pending. This Ansible role and its defaults are unchanged. The accepted port checks the shared client
alias, bucket configuration, user credentials, policies and attachments before
writing. It uses signed requests with a private temporary client configuration,
never an IAM export. Disabled users and unknown/transport failures stop the run.
Existing immutable versioned policies are not overwritten. The explicit
weeknotes-policy maintenance rollback is outstanding tracked conversion work;
the current legacy command remains available until its guarded equivalent is
implemented and qualified. This is not a permanent workflow exception or a new
acknowledgement requirement.

The port manages each data root's owner/group/mode without recursive chmod or
chown; a read-only foreign-owner search refuses a mismatched descendant.
On a healthy store it walks every descendant metadata entry, with no separate
probe timeout; it reads no object bodies.
It leaves objects, replication, lifecycle jobs, backup identities and unrelated
aliases outside deployment ownership. False bucket-versioning input never
disables an existing setting. These are deliberate convergence changes, not
claims that the Ansible role has become write-free on repeat.

The legacy pinned server/client URLs returned HTTP 410 during research. Exact verified
read-only binary copies are permitted for owned fixtures; no replacement release
or artifact source is selected implicitly. ARM/QEMU CLI research is emulated,
not native deployment qualification. The later offline x86 KVM matrix completed
28 phases with 13 strict zero-change repeats and every-phase foreign-alias
equality; inventory adoption remains pending.
The pyinfra client uses the official GitHub `minio/mc` release asset
`mc.linux-amd64.RELEASE.2025-08-13T08-35-41Z`, anonymously verified at 30,535,864 bytes
and unchanged SHA256 `01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891`.
Matching clients do not download. This source-only correction leaves this role's
Ansible/custom URL inputs unchanged; the server source is still unavailable.

The native-qualified port includes current-root host-local IAM admission and normal
known-owned client/service recovery. A missing pinned client is installed, or a
known inactive unit with the declared valid configuration is started, before a
complete IAM check. These prerequisite changes remain reported if later IAM
admission fails. Desired root credentials are applied with a change-gated restart
and rechecked before alias/IAM writes. Unknown/foreign state remains a refusal;
no acknowledgement flag is added. The owned native matrix exercised missing
client recovery (one installed artifact), stopped-unit recovery (one start) and
root rotation (three managed operations/no upload), each followed by a strict
zero-change repeat. Disabled-IAM refusals after prerequisites retain those
actual partial changes.

Exact-policy identities may not declare superseded-policy retirement; that path
is limited to additive identities. This documentation does not change the legacy
Ansible workflow: its root environment notifies a deferred restart, but bootstrap
uses desired credentials before that handler. The original owned root-rotation
case actually failed after writing the new environment but before restarting
the old-credential process. Pyinfra safely refused that untouched half-applied
state before writes; it is not claimed to repair every historical partial state.
Original normal/missing-client/stopped-service cases succeeded with real writes.

Public artifact 1249bd0 was installed noneditably in a fresh Ubuntu24 independent
KVM guest; all 684 installed resources matched Git, KVM was present/enabled, and
the guest had loopback only. Final exit 0 and exact owned container/image cleanup
were verified. Earlier failed attempts remain retained. This is synthetic native
proof, not production IAM/object access, global zero-I/O or inventory acceptance.
An independent original S4 lag probe ran afterward with its own receipt and
expected marker/status writes; it does not extend MinIO deployment ownership.

## Upgrades

The currently pinned URLs are unavailable as noted under
“Version Pinning & Checksums” above. Confirm availability
of the intended exact artifact before following these steps.

To upgrade MinIO:

1. Check latest release: https://github.com/minio/minio/releases
2. Get new checksum (see Version Pinning section)
3. Update playbook variables:
   ```yaml
   minio_version: "RELEASE.2025-10-15T17-29-55Z.hotfix.c392ab039"
   minio_checksum: "sha256:newchecksum..."
   ```
4. Once the reviewed artifact is available, rerun deployment; the role downloads
   the verified binary and restarts the service.

## Troubleshooting

### Service won't start

```bash
# Check logs
journalctl -u minio -f

# Check systemd status
systemctl status minio

# Verify ports not in use
sudo lsof -i :9001
sudo lsof -i :9002
```

### Checksum validation fails

```bash
# Verify checksum format
echo "sha256:abc123..." | grep -E '^sha256:[a-f0-9]{64}$'

# Get correct checksum
curl -s "https://dl.min.io/server/minio/release/linux-amd64/archive/minio.RELEASE.xxx.sha256sum"
# or hotfix stream:
curl -s "https://dl.min.io/server/minio/hotfixes/linux-amd64/archive/archive/minio.RELEASE.xxx.hotfix.yyyyyyyyy.sha256sum"
```

### Bootstrap fails

```bash
# Test mc connectivity
mc alias set test http://127.0.0.1:9001 <USER> <PASS>
mc admin info test

# Check credentials
mc admin user list test
```

## Examples

### Basic Internal-Only Deployment

```yaml
- role: local.ops_library.minio_deploy
  vars:
    minio_root_user: "{{ vault_minio_user }}"
    minio_root_password: "{{ vault_minio_password }}"
    minio_version: "RELEASE.2024-10-02T17-50-41Z"
    minio_checksum: "sha256:abc123..."
```

### Production with Bootstrap

See "With Bootstrap" example in Quick Start section.

### Multi-Disk Setup

```yaml
minio_data_dirs:
  - /mnt/disk1/minio
  - /mnt/disk2/minio
  - /mnt/disk3/minio
  - /mnt/disk4/minio
```

Note: MinIO requires at least 4 drives for erasure coding.

## Dependencies

- Target OS: Debian/Ubuntu with systemd
- Ansible: >= 2.9
- Root/sudo access on target

## License

MIT

## Author

ops-library team
