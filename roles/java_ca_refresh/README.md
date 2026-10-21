# java_ca_refresh

Refresh a stale Debian/Ubuntu Java CA store after the OS CA package has removed
the affected eMudhra trust roots. The supported `update-ca-certificates --fresh`
hook removes obsolete distribution aliases and retains local Java aliases.
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

Requires installed `ca-certificates-java`, functional `keytool`, the standard
`changeit` trust-store password, and patched OS trust. A pending marker survives interrupted refresh/restart runs and is cleared only
after verification, all selected restarts, and port readiness succeed.
A second successful run makes no
changes and does not restart services. Check mode inspects live state but does
not refresh or restart. Restarting services discards already-loaded SSL contexts;
TCP readiness should be supplemented with each application's normal health test.
