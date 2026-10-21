# security_trust_remediate

Narrow Debian/Ubuntu trust-store incident remediation. Installs an inventory-pinned
`ca-certificates` revision, the checksum-pinned `uv_install` release, and offline,
hash-verified certifi/pip wheels in an explicit list of existing virtual
environments. It never adds certifi or pip, overwrites system Python, syncs an
application lock, runs migrations, or updates unrelated APT packages.

Supply `security_trust_ca_version`, `security_trust_wheels` (two entries with
`package`, `src`, `name`, `sha256`), and `security_trust_environments` entries with
`path`, `services`, and `health_urls` (`url`, optional `headers` and `status_codes`).
An empty service list is appropriate for inactive/tool environments. Live workers
must list the web application's health URL too. Services restart serially; each
restart must pass its health probes before proceeding. Inventory controls the
host rollout order with `serial: 1`.

Defaults pin certifi 2026.10.19 and pip 26.2.2, use `/usr/local/bin/uv`, retain
root-only metadata and complete environment tar snapshots under
`/var/backups/security-trust-remediation`, and stage public wheels under
`/var/cache/security-trust-remediation`. Never put credentials in health URLs.
The controller needs `packaging` (provided by Ansible's dependencies).

Preflight evaluates installed base dependency requirements with remote Python
markers. Extras are not recorded in installed metadata: selected extra constraints
and reproducibility must be fixed in owning lockfiles. Python <3.10 cannot install
the pinned pip. Such environments must be handled separately, never bypassed.
The role rejects environments exposing system site-packages. Application-owned
interpreters run as the application owner; distro Python independently verifies
the reported bundle files without importing application code. Persistent restart
markers survive interruptions and clear only after all services pass health.
Completion filenames include a digest of the CA/certifi/pip target versions, so
a prior incident completion cannot suppress a later target revision restart.
OS CA package changes also require restarts.

`security_trust_lockfiles` optionally supplies reviewed deployed lock replacements
(`path`, `src`, `original_sha256`, `sha256`). Exact drift guards and a parsed TOML
comparison allow only the certifi package stanza to change; the role preserves
the original lock and runs `uv lock --check --offline` before any restart. This
prevents services launched via `uv run` from reverting the security update.

The role verifies actual certifi and pip bundles contain neither emSign ECC Root
CA - G3 nor AAA Certificate Services, as well as the OS default SSL context.
Distribution-unbundled certifi/pip use the OS bundle and must stay distro managed.

A failed update or probe stops the rollout. Snapshots are evidence and an
operator-directed rollback source; automatic rollback would reintroduce vulnerable
trust. Preserve snapshot paths from logs; investigate before restoring. Inactive
archived application backups are excluded and must be remediated upon restore.
Hosts without selected environments or lockfiles skip the packaging client
installer. The absolute `security_trust_uv_bin` must end in `/uv`; its directory
selects the installer destination, so installation and execution use the same file.

`--check` reports package/file changes but skips environment execution and restarts.

Example private orchestration:

```yaml
- hosts: incident_linux
  serial: 1
  roles:
    - local.ops_library.security_trust_remediate
```
