# ca_trust_consumers

Finish a system CA store fix for the long-running TLS clients on a Debian or
Ubuntu host that a package update alone does not reach:

- **Node.js** ignores the system store by default: it verifies against the
  Mozilla store compiled into the binary. The role sets
  `NODE_OPTIONS=--use-openssl-ca`, which *replaces* that store with OpenSSL's
  default store (the system one), for login/SSH/sudo/cron sessions through
  `/etc/environment` and for listed Node.js services through a systemd
  drop-in.
- **Go services** (and other clients that load roots once per process) keep
  the roots they loaded at startup. The role restarts listed services whose
  main process started before the CA bundle last changed, one at a time, each
  checked healthy before the next.

It was written for the October 2026 eMudhra intermediate CA key compromise
([incident tracker](https://emudhra.we-have-a-problem.com/)); the forbidden-root
defaults are that incident's four roots.

## Safety model

- **CA readiness gate first.** Nothing is written or restarted unless the CA
  package is at least `ca_trust_consumers_ca_min_version` *and* no forbidden
  root (by SHA-256 fingerprint) is visible in the bundle file,
  `/etc/ssl/cert.pem` or any file of `/etc/ssl/certs` / `/etc/pki/tls/certs` —
  the set Go's `crypto/x509` reads on Linux and Node.js's OpenSSL resolves to. The role does not update the
  CA package itself.
- **Existing configuration is kept.** An existing `NODE_OPTIONS` in
  `/etc/environment` or in the unit's own `Environment=` is preserved and the
  flag appended. `EnvironmentFile=` values take precedence over a drop-in, so
  the role fails closed instead of parsing them: any mention of `NODE_OPTIONS`
  in such a file (an assignment in any spelling, a continuation or a comment),
  a wildcard pattern or an unreadable file makes it fail and name the file;
  values are never printed. `--use-bundled-ca` already present also fails,
  because Node.js refuses both selectors together.
- **Only running units are restarted**, and only when their main process
  started before the CA bundle's modification time or, for a Node.js
  service, while one of its running Node.js processes lacks the flag. Both
  are read from the host, so a rerun after an interrupted run makes the same
  decisions. A stopped or disabled unit is never started; it still gets its
  drop-in, so a later start uses the system store.
- **No side-loaded changes.** Before anything is written the role fails if a
  listed unit already awaits `daemon-reload` (its own drop-in change triggers
  one, which would load that pending change unseen). A restart is refused (the
  role fails, naming the cause) when it would also activate something staged
  since the process started: a replaced executable, a unit file, drop-in or
  `EnvironmentFile=` file changed, or a listed `guard_paths` entry (static
  config, a release symlink) newer than the process — a symlink counts when
  either the link or its target changed. Unit properties the role cannot
  parse unambiguously (drop-in or environment-file paths with blanks in an
  unexpected shape) also refuse the restart.
  `allow_staged_changes: true` on the entry overrides this.
- **No secrets in output.** `/etc/environment` and `systemctl cat` output are
  read with `no_log` and written without diffs; checks of environments and
  environment files print only file names, PIDs and yes/no.
- **Effective value checked.** After writing a drop-in the role checks the
  unit's effective `Environment=` (a later drop-in could override it) and
  `UnsetEnvironment=`, also for stopped units, and fails unless the flag is
  effective. The drop-in is named `99-…` to apply last.
- **Serial restarts with checks.** After each restart the role waits for an
  active, newer main process and runs the unit's optional `health_command`
  before moving on. The pre-restart PID, start time, executable and its
  SHA-256 are printed for the run log; a restart changes no file, so there is
  nothing else to roll back.
- **Runtime proof for Node.js services.** After restarts, every Node.js process
  in each listed unit's cgroup must carry the flag in its actual environment
  (only `pid=… flag=yes/no` is printed).
- **Report-only mode.** `ca_trust_consumers_restart: false` writes the trust
  configuration but only reports which units would be restarted (the runtime
  flag check then reports instead of failing). Check mode (`--check`) changes
  nothing and also only reports.

## Why these mechanisms

- `--use-system-ca` (Node.js 22.15+/23.8+) and `NODE_EXTRA_CA_CERTS` *add*
  certificates to the bundled store, so the bundled copy of a distrusted root
  stays trusted. Runtime tests on Node.js 22.21, 24.17 and 24.22 showed
  `--use-system-ca` still accepting the compromised test chains on a host
  whose system store was already fixed, while `--use-openssl-ca` rejected all
  twelve and accepted ordinary sites. `SSL_CERT_FILE`/`SSL_CERT_DIR` are not
  needed: the official and NodeSource builds' bundled OpenSSL has
  `OPENSSLDIR "/etc/ssl"`, so it reads `/etc/ssl/cert.pem` (absent on
  Debian/Ubuntu) and looks up issuers in `/etc/ssl/certs` by subject hash.
- OpenSSL caches the issuers it has looked up in a process, so a Node.js
  service started before the store changed is restarted like a Go service.
- pam_env does not apply to systemd services, hence the per-unit drop-in.
- sudo resets the environment, and Debian 13's sudo PAM stack (unlike
  Ubuntu's) does not read `/etc/environment`, so `sudo -u <app>` sessions —
  how Ansible and pyinfra run `become` steps such as `npm ci` or `yarn
  install` — would lose the flag. A sudoers drop-in
  (`/etc/sudoers.d/ca-trust-consumers`, validated with `visudo -cf`) sets
  `Defaults env_file=` to a root-owned file holding the same `NODE_OPTIONS`.
  Unlike `env_keep`, this never passes a caller's own `NODE_OPTIONS` through.
  sudoers takes one `env_file`, so the role reads the effective policy with
  sudo's own exporter (`cvtsudoers -c /dev/null -i sudoers -d all -f json`:
  real grammar, includes followed, its own configuration file ignored so no
  filter can hide an entry) and refuses unless there is no `env_file` at all or exactly one
  unbound `env_file` equal to its own file; a scoped, negated or foreign
  `env_file`, or a policy `cvtsudoers` cannot export, also refuses. It checks
  again after writing the drop-in. Only a verdict is printed, never the policy.
  The drop-in is a separate file the owning service role does not manage, so
  application redeploys keep it.
- Go's `crypto/x509` loads system roots once per process (`sync.Once`). Go
  1.26.10 and 1.27.3 additionally block the compromised intermediates
  in-process; binaries built with older Go rely on the system store alone and
  only see a fixed store after a restart.

## Requirements

- Debian 12/13 or Ubuntu 24.04 with systemd ≥ 252 (`--timestamp=unix`), cgroup
  v2, `python3` on the host.
- The play must gather facts (`os_family`, `date_time`).

## Role variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ca_trust_consumers_ca_min_version` | `""` (required) | Minimum `ca-certificates` dpkg version carrying the fix. |
| `ca_trust_consumers_ca_package` | `ca-certificates` | Package checked by the gate. |
| `ca_trust_consumers_forbidden_root_sha256` | four eMudhra-incident roots | Upper-case SHA-256 certificate fingerprints that must not be visible. |
| `ca_trust_consumers_root_paths` | bundle, `/etc/ssl/cert.pem`, `/etc/ssl/certs`, `/etc/pki/tls/certs` | Files and directories scanned. |
| `ca_trust_consumers_ca_bundle` | `/etc/ssl/certs/ca-certificates.crt` | Its mtime marks the last CA store update. |
| `ca_trust_consumers_node_flag` | `--use-openssl-ca` | Flag merged into `NODE_OPTIONS`. |
| `ca_trust_consumers_node_cli` | `false` | Manage `NODE_OPTIONS` in `/etc/environment`. |
| `ca_trust_consumers_environment_file` | `/etc/environment` | pam_env file. |
| `ca_trust_consumers_node_cli_sudo` | `true` | With `node_cli`, also configure sudo sessions (skipped when `ca_trust_consumers_visudo` is absent). |
| `ca_trust_consumers_sudo_env_file` | `/etc/ca-trust-consumers/sudo.env` | Root-owned file sudo reads (`env_file`). |
| `ca_trust_consumers_sudoers_dropin` | `/etc/sudoers.d/ca-trust-consumers` | Drop-in setting `Defaults env_file=`; its name must not contain a dot. |
| `ca_trust_consumers_sudoers` | `/etc/sudoers` | Main sudoers file given to `cvtsudoers` (includes are followed). |
| `ca_trust_consumers_cvtsudoers` | `/usr/bin/cvtsudoers` | sudo's exporter; its absence refuses the sudo step. |
| `ca_trust_consumers_visudo` | `/usr/sbin/visudo` | Validates the drop-in. |
| `ca_trust_consumers_node_units` | `[]` | Node.js services: `{name, health_command?, guard_paths?, allow_staged_changes?}`. Get a drop-in (also when inactive), restart while a running process lacks the flag or roots are old, runtime-verified. |
| `ca_trust_consumers_node_dropin_name` | `99-ca-trust-node.conf` | Drop-in file name under `/etc/systemd/system/<unit>.d/`. |
| `ca_trust_consumers_systemd_dir` | `/etc/systemd/system` | Parent of the `<unit>.d/` drop-in directories. |
| `ca_trust_consumers_restart_units` | `[]` | Other TLS clients: `{name, health_command?, detached?, guard_paths?, allow_staged_changes?}`. Restarted when started before the bundle changed. |
| `ca_trust_consumers_restart` | `true` | `false` = report which units would be restarted. |
| `ca_trust_consumers_health_retries` / `_health_delay` | `12` / `5` | Polling for the new process and the health command. |
| `ca_trust_consumers_reconnect_timeout` | `180` | Seconds to wait for the connection after a detached restart. |

Unit names must end in `.service` and appear in only one list. List order is
restart order: put the network path the controller uses (for example
`tailscaled.service`, with `detached: true`) last, and connect to that host over
a different path for the run.

## Example

```yaml
- name: Finish CA trust for long-running clients
  hosts: staging
  become: true
  roles:
    - role: local.ops_library.ca_trust_consumers
      vars:
        ca_trust_consumers_ca_min_version: "20250419+deb13u1"
        ca_trust_consumers_node_cli: true
        ca_trust_consumers_node_units:
          - name: mastodon-streaming.service
            health_command: curl -fsS -o /dev/null http://127.0.0.1:10043/api/v1/streaming/health
        ca_trust_consumers_restart_units:
          - name: gotosocial.service
            guard_paths: [/opt/gotosocial/current, /etc/gotosocial/config.yaml]
            health_command: curl -fsS -o /dev/null http://127.0.0.1:10070/readyz
          - name: traefik.service
            guard_paths: [/etc/traefik/traefik.toml]
            health_command: ss -ltnH 'sport = :443' | grep -q .
          - name: tailscaled.service
            detached: true
            health_command: >-
              tailscale status --json | python3 -c 'import json,sys;
              sys.exit(json.load(sys.stdin)["BackendState"] != "Running")'
```

## Verifying

The role's own checks prove configuration and process state. To prove trust
behaviour, run a TLS client against the incident's test hosts (for example
`https://dv-g3b-emudhra.we-have-a-problem.com/`, twelve hosts in total) with
the same runtime and environment: it must fail certificate verification, while
ordinary sites still succeed.

## Removing

When every Node.js runtime in use ships the upstream fix, delete the
`NODE_OPTIONS` line (or the flag) from `/etc/environment`, the sudo pair
`/etc/sudoers.d/ca-trust-consumers` and `/etc/ca-trust-consumers/sudo.env`, and the
`/etc/systemd/system/<unit>.d/99-ca-trust-node.conf` drop-ins, then
`systemctl daemon-reload` and restart the units. Keeping the flag is also
fine: it makes Node.js follow future system store updates.

## Limitations

- Processes outside systemd services and pam_env sessions (for example a Node
  CLI started by a service as a child with a scrubbed environment) are not
  covered.
- A tool that sets its own `NODE_OPTIONS` replaces the inherited one.
- `update-ca-certificates` rewrites the bundle on every run, so a later run of
  this role after another store refresh restarts the listed units again.
- Containers are not touched; their images carry their own stores and runtimes.
