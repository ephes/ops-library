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

See [defaults/main.yml](defaults/main.yml) for complete list.

## Version Pinning & Checksums

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

## Upgrades

To upgrade MinIO:

1. Check latest release: https://github.com/minio/minio/releases
2. Get new checksum (see Version Pinning section)
3. Update playbook variables:
   ```yaml
   minio_version: "RELEASE.2025-10-15T17-29-55Z.hotfix.c392ab039"
   minio_checksum: "sha256:newchecksum..."
   ```
4. Rerun deployment - role will download new binary and restart service

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

See [LICENSE](../../LICENSE)

## Author

ops-library team
