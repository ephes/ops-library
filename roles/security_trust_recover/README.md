# security_trust_recover

Recover an interrupted certifi replacement whose owner cannot remove old root-owned
bytecode. Run this role before retrying `security_trust_remediate`; it does not
restart services or clear pending restart evidence. It never changes source code,
rewrites metadata, inserts a previously absent distribution or changes ownership
outside exact generated cache entries. Existing root-only full-environment backup
and SHA256-pinned `before.json` prove the previous certifi installation.

`security_trust_recover_entries` is an explicit list with `path`, `owner`, `before`,
`before_sha256`, `archive_sha256`, and exact `cache_paths`. The default empty list is a no-op.
`security_trust_recover_wheel` and `security_trust_recover_sha256` select the locally
staged certifi2026.10.19 wheel, whose digest is validated before ownership changes.
Prior dependency metadata must permit that version. `security_trust_recover_version` defaults to 2026.10.19 and
`security_trust_recover_uv_bin` defaults to `/usr/local/bin/uv`. The normal-role
hook passes its own staged wheel path, digest, target version and UV executable
explicitly. An already fixed distribution makes recovery a no-op even after UV
has removed old cache paths; a newer recorded version is never downgraded.
Package installation runs as
the environment owner through the configured UV executable, offline and without dependencies.
Check mode validates all evidence and previews ownership changes without installing.

Example orchestration:

```yaml
- hosts: incident_hosts
  roles:
    - local.ops_library.security_trust_recover
    - local.ops_library.security_trust_remediate
```

Keep the original backup and before digest across retries. An interrupted uv
uninstall may remove dist-info before failing; the prior snapshot, rather than
current metadata absence, is the authority for this specific restoration. Retain
pending restart markers until the normal remediation role verifies fresh bundle
contents and completes every service health check.

For a known cache anomaly before an uninterrupted update, an environment entry in
`security_trust_remediate` may set exact `cache_recovery_paths`. The normal role
creates its full archive and before record first, hashes both, then invokes this
recovery role before its ordinary package replacement. Omit this optional field
for all other environments.

Run the required integration gate explicitly with `just test-security-trust-recover`.
It requires Docker, the documented cached Debian fixture, community.docker and
wheel/tool download access; every actual caller test must execute without skips.
The default contributor validation path does not require these optional Docker
prerequisites.
