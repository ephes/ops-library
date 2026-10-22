# java_ca_refresh

Refresh a stale Debian/Ubuntu Java CA store after the OS CA package has removed
the affected eMudhra trust roots. After refreshing OS PEM state, the packaged
`update-ca-certificates-java-fresh` dpkg trigger removes obsolete distribution
aliases and retains local Java aliases.
The role refuses to run while either affected OS PEM link remains enabled.
It does not edit signed application bundles or install Java.

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `java_ca_refresh_services` | `[]` | Explicit JVM systemd services to restart after a refresh |
| `java_ca_refresh_ports` | `[]` | Local TCP ports to await after verification |

## Example

```yaml
- hosts: java_servers
  become: true
  roles:
    - role: local.ops_library.java_ca_refresh
      java_ca_refresh_services: [example-java.service]
      java_ca_refresh_ports: [8443]
```

Requires installed `ca-certificates-java`, functional `keytool`, `dpkg-trigger`
and `dpkg` (with package locks available), the standard
`changeit` trust-store password, and patched OS trust. A pending marker survives interrupted refresh/restart runs and is cleared only
after verification, all selected restarts, and port readiness succeed.
A second successful run makes no
changes and does not restart services. Check mode inspects live state but does
not refresh or restart. Restarting services discards already-loaded SSL contexts;
TCP readiness should be supplemented with each application's normal health test.

Ubuntu's `update-ca-certificates --fresh` rebuilds the OS bundle but does not pass
`--fresh` to hook arguments. The role therefore explicitly schedules the packaged
`update-ca-certificates-java-fresh` dpkg trigger and processes only
`ca-certificates-java` before verifying stale aliases are absent. This uses the
distribution fresh-rebuild implementation rather than editing the store directly.

Before a refresh the role retains a root-only, SHA-256-addressed copy of the
original store plus its RFC certificate identity listing under
`/var/lib/ops-library-java-ca-refresh/`. It verifies every non-`debian:` alias and
its certificate bytes remain identical after the package rebuild. Distribution
aliases are intentionally reconciled against enabled OS PEM certificates; obsolete
distribution aliases may be removed by the packaged fresh hook. The pending marker
survives any failed trigger, verification, restart or readiness check. dpkg locking
is respected: a competing package operation causes a safe failure for operator
retry, without bypassing locks or restarting JVMs before verified trust.

Check mode previews the recovery directory and trigger/restart plan, but skips
backup copies because their destination directory may only be planned. It never
creates a backup, changes trust, or restarts JVMs during that preview.

The active `baseline.rfc` is anchored before the pending marker and retained across
retries; recovery compares custom identities against this saved pre-mutation
baseline, never an already-modified store. A pending run cannot overwrite an existing baseline. A legacy pending marker
with stale aliases still present and no baseline adopts the current listing,
retaining the checksum-addressed backup for provenance.
Recovery with roots already absent but no baseline fails closed for reconciliation.
A new refresh with no pending marker may establish a new baseline; the immutable
checksum-addressed store/RFC backup remains available for provenance. Custom
identity comparison ignores listing order.
