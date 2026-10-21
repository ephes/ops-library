# metrics_httpd_switch (internal helper)

Selects, per endpoint unit, the role's Python script or the pinned Rust
`metrics-httpd` binary, and verifies the selection. It is the switch of
[`rust/metrics-httpd/PLAN.md`](../../rust/metrics-httpd/PLAN.md) section 7
(slice S5a). The consumer role keeps its unit file and its Python script
exactly as they are; Rust is selected by one systemd drop-in that replaces
`ExecStart=`:

```ini
# /etc/systemd/system/<service>.service.d/metrics-httpd-impl.conf
# Managed by ops-library metrics_httpd_switch: selects the Rust metrics-httpd.
# Remove this file (daemon-reload, restart) to fall back to Python.
[Service]
ExecStart=
ExecStart=/opt/metrics-httpd/<version>/metrics-httpd json-file --bind … --realm backup-metrics --server-name backup-metrics-httpd/0.1
```

User, group, sandbox, IP filter, restart policy and ordering stay the unit's.
The binary comes from the shared install root `/opt/metrics-httpd/<version>/`
of the internal helper [`rust_release_binary`](../rust_release_binary/README.md)
(install, pin, prune).

Consumers: `backup_metrics_endpoint`, `storage_metrics_endpoint`,
`thermal_metrics_endpoint`, `tailscale_metrics_endpoint`,
`dns_metrics_endpoint` (S5a); `metrics_endpoint`, `os_apt_maintenance`,
`dns_deploy` (DDNS), `openclaw_deploy` (S5b); `logyard_deploy`,
`static_site_deploy` (S5c); ops-control's `torrent_vpn_metrics_endpoint` (S5d).

## Selecting the implementation (inventory)

Fleet variables (ops-control `group_vars/all.yml`), read by every consumer:

```yaml
metrics_httpd_impl: python            # python | rust; fleet default
metrics_httpd_rust_version: "0.1.0"   # release tag metrics-httpd-v0.1.0
metrics_httpd_rust_sha256: "<64 hex>" # sha256 of the release archive
```

Each consumer has `<role>_impl` (default `{{ metrics_httpd_impl |
default('python') }}`), overridable per host for a canary, e.g.
`tailscale_metrics_endpoint_impl: rust` in `host_vars/staging.yml`.
With a version set, the release is installed and `--check-config` runs even
while the unit stays on Python, so the binary can be installed ahead of the
switch (PLAN.md 10.2).

Rollback (PLAN.md 7.5): set `<role>_impl: python` (or `metrics_httpd_impl`)
and deploy; the drop-in disappears and the unit restarts the Python script
that every deploy keeps installed. Emergency, on the host as root:
`rm /etc/systemd/system/<unit>.service.d/metrics-httpd-impl.conf &&
systemctl daemon-reload && systemctl restart <unit>`, then flip the inventory
before the next deploy. Rust to Rust: pin the previous version and sha256;
it is still installed (pins and `keep_versions`).

## Use from a consumer role

The inputs are set once (e.g. as `vars:` of the role's deploy block) and two
task files are included:

```yaml
- name: Deploy backup metrics endpoint
  when: backup_metrics_endpoint_enabled | bool
  vars:
    metrics_httpd_switch_impl: "{{ backup_metrics_endpoint_impl }}"
    metrics_httpd_switch_service_name: "{{ backup_metrics_endpoint_service_name }}"
    metrics_httpd_switch_validate_user: "{{ backup_metrics_endpoint_user }}"
    metrics_httpd_switch_validate_group: "{{ backup_metrics_endpoint_group }}"
    metrics_httpd_switch_argv: [json-file, --bind, "{{ backup_metrics_endpoint_bind }}", …]
    metrics_httpd_switch_unit_sandbox: [NoNewPrivileges=yes, ProtectSystem=strict, ProtectHome=yes, PrivateTmp=yes]
    metrics_httpd_switch_notify: [reload systemd, restart backup-metrics-endpoint]
    metrics_httpd_switch_python_script: "{{ backup_metrics_endpoint_server_path }}"
    metrics_httpd_switch_probe_bind: "{{ backup_metrics_endpoint_bind }}"
    metrics_httpd_switch_probe_port: "{{ backup_metrics_endpoint_port }}"
    metrics_httpd_switch_probe_path: "{{ backup_metrics_endpoint_path }}"
    metrics_httpd_switch_probe_realm: backup-metrics
    metrics_httpd_switch_ip_address_allow: [localhost, 100.64.0.0/10]
  block:
    # ... unit file, htpasswd, script ...
    - name: Select the HTTP server implementation
      ansible.builtin.include_role:
        name: local.ops_library.metrics_httpd_switch
        tasks_from: select
    # ... flush_handlers, enable and start the unit ...
    - name: Apply a pending implementation switch before verifying it
      ansible.builtin.meta: flush_handlers
    - name: Verify the HTTP server implementation
      ansible.builtin.include_role:
        name: local.ops_library.metrics_httpd_switch
        tasks_from: verify
```

Including the role without `tasks_from` fails.

## `tasks_from: select`

Runs after the unit file is rendered (and after the files `--check-config`
reads, such as the htpasswd file), before the unit is enabled and started.

1. Asserts what the switch back to Python needs: `impl` is `python` or
   `rust`, the service name is a pin consumer name (lower-case letters,
   digits, `-`, `_`) and `notify` is a list. The inputs only the Rust path
   uses must be valid for `rust` (the play stops, nothing is switched): every
   `argv` element is a non-empty string or integer without `%` (systemd
   specifiers), `$` (environment expansion), `"`, `\` or a control
   character, `argv[0]` is a metrics-httpd mode and `--check-config` is not
   in it; the sandbox is a `Key=Value` list without `User=`/`Group=`; user,
   group and install root are set; a release version with a 64-hex sha256
   (or a local archive). With `python` a problem there only warns (an
   ignored failed task) and skips `--check-config`, and the release inputs
   are left to the install, which warns too: a broken input never blocks
   the switch back. Malformed release values (an integer, a list) are
   normalised to text first.
2. Reads the drop-in to remember the binary it selected before this run
   (verify protects that version from prune).
3. `impl: python`: removes the drop-in first, so the switch back never waits
   on a Rust download or check.
4. With a version set (independent of `impl`): `rust_release_binary`
   `install` (`fail_hard` only for `rust`; for `python` a broken release
   warns, `ignored=1`, and the play continues).
5. If the binary is installed: `<binary> <argv> --check-config` through
   `systemd-run --wait --pipe --collect --quiet` as the unit's user and group
   with `unit_sandbox` as `--property=` values. It binds nothing and prints
   no hash or password. Failure stops the play for `rust` (nothing was
   switched) and warns for `python`.
6. `impl: rust`: templates the drop-in (`root:root 0644`, directory `0755`).
   `ExecStart=` holds the versioned binary and `argv`; a word with a space,
   `'` or `;` is written in double quotes (systemd's word splitting gives
   back exactly `argv`). The version is part of the line, so a version
   change or an impl flip changes the file and an unchanged deploy changes
   nothing.

A drop-in change notifies `notify` (the consumer's `reload systemd` and
restart handlers). In check mode nothing is installed or written; the
`--check-config` runs only when the binary is already installed.

## `tasks_from: verify`

Runs after `meta: flush_handlers` (the restart happened); skipped in check
mode. Every check retries for about 30 s (`verify_retries` ×
`verify_delay`).

1. The unit is `active` with a `MainPID`; `rust`: `readlink
   /proc/<pid>/exe` is the versioned binary (either spelling of the install
   root); `python`: `/proc/<pid>/cmdline` contains `python_script`.
2. An unauthenticated `GET http://<probe_bind>:<probe_port><probe_path>` from
   the host (no proxy, no redirects, no `.netrc`): `unauthorized` expects 401 with
   `WWW-Authenticate: Basic realm="<probe_realm>"` (json-file, script,
   apt-state); `logyard-health` 200 with a JSON object holding `status`;
   `static` 200. The probe's source address is the bind address (the
   unspecified address is probed on loopback), so it is skipped with a message
   when the unit's `IPAddressAllow=` (`ip_address_allow`) does not cover it,
   and when the bind address is a host name rather than an IP address (only
   a Python unit can have one: `--check-config` refuses it for Rust). The
   probe waits `probe_timeout` seconds for the answer.
   No credential is used anywhere in the switch.
3. Only then: `rust_release_binary` `pin` (`state: present` with the version
   for `rust`; `state: absent` for `python`, which keeps the last version as
   the unit's rollback pin) and `prune` with `protect` = the live executable
   and the binary the drop-in named before this run.

A failed check stops the play before any pin moves or anything is pruned.

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `metrics_httpd_switch_impl` | `""` | `python` or `rust` (required). |
| `metrics_httpd_switch_service_name` | `""` | Unit name without `.service`; also the pin consumer. |
| `metrics_httpd_switch_argv` | `[]` | metrics-httpd command line after the binary (PLAN.md 7.3). |
| `metrics_httpd_switch_validate_user` / `_validate_group` | `""` | The unit's `User=`/`Group=`; `--check-config` runs as them. |
| `metrics_httpd_switch_unit_sandbox` | `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes` | `systemd-run --property` values mirroring the unit (append `ReadOnlyPaths=`, `Environment=`). |
| `metrics_httpd_switch_notify` | `[]` | Handlers notified when the drop-in changes. |
| `metrics_httpd_switch_version` | `metrics_httpd_rust_version` or `""` | Release version; empty installs nothing (Python only). |
| `metrics_httpd_switch_sha256` | `metrics_httpd_rust_sha256` or `""` | sha256 of the release archive. |
| `metrics_httpd_switch_local_archive` | `metrics_httpd_rust_local_archive` or `""` | Controller archive instead of the download (development). |
| `metrics_httpd_switch_install_root` | `/opt/metrics-httpd` | Shared install root (foundation 6.1). |
| `metrics_httpd_switch_python_script` | `""` | Path the Python process's command line must contain. |
| `metrics_httpd_switch_probe_bind` / `_probe_port` / `_probe_path` | `""` / `0` / `""` | Where the probe goes. |
| `metrics_httpd_switch_probe_expect` | `unauthorized` | `unauthorized`, `logyard-health` or `static`. |
| `metrics_httpd_switch_probe_realm` | `""` | Realm of the 401 (`unauthorized`). |
| `metrics_httpd_switch_probe_timeout` | `5` | Seconds the probe waits for the answer (whole seconds; `logyard_deploy` raises it to its Loki and `systemctl` timeouts). |
| `metrics_httpd_switch_ip_address_allow` | `[any]` | The unit's `IPAddressAllow=` values (`any`, `localhost`, `link-local`, `multicast`, addresses, prefixes). |
| `metrics_httpd_switch_verify_retries` / `_verify_delay` | `15` / `2` | Retries of the process check and of the probe. |
| `metrics_httpd_switch_keep_versions` | `3` | Newest versions prune keeps on top of every pin and the live versions. |
| `metrics_httpd_switch_systemd_dir`, `_proc_root`, `_owner`, `_group`, `_version_check_user` | `/etc/systemd/system`, `/proc`, `root`, `root`, `validate_user` | Test-only knobs for the unprivileged localhost tests. |

Facts it leaves: the `rust_release_binary_*` facts of install, pin and prune;
internal `_metrics_httpd_switch_*` facts (reset by every `select`).

## Rendering outside Ansible

ops-deploy renders `templates/metrics-httpd-impl.conf.j2` byte-identically
for the pyinfra-deployed units (PLAN.md 7.4) with plain Jinja2
(`trim_blocks`, `keep_trailing_newline`) and two variables:
`metrics_httpd_impl_binary` (the versioned binary) and
`metrics_httpd_impl_argv` (the argv as strings, already checked by the rules
of select step 1). The template uses no Ansible filter.

## Tests

`just test-metrics-httpd-switch` (part of `just test`) runs
`tests/test_metrics_httpd_switch.py` and
`tests/test_metrics_httpd_switch_logyard_static.py` (the same checks for the
inputs of `logyard_deploy` and `static_site_deploy`, whose `--check-config`
sandbox is their unit's own `[Service]` lines). The first holds unit tests of
`plugins/filter/metrics_httpd.py`; the drop-in rendered with plain Jinja2 and
split back like systemd; static checks of the consumer roles (S5a and S5b);
`ansible-playbook` runs that render each consumer's argv, drop-in and base
unit from its defaults (the argv equals the fixture argv of the role's Python
script in `rust/metrics-httpd/fixtures/`; drop-ins and the unchanged
base units equal the goldens in `tests/fixtures/metrics_httpd_switch/`); and
`ansible-playbook` runs of select and verify on localhost with a fake
release archive, fake `systemd-run` and `systemctl`, a fake `/proc` and a
probe server (switch, idempotent re-run, upgrade, switch back, pins and
prune, quoting, refused `--check-config`, refused and warned installs,
input refusals, failed process check, wrong realm, open endpoint, skipped
probe, check mode, a switch under `--tags` through a tagged include as
`dns_deploy` runs it). On macOS the runs need Homebrew coreutils (`gmv`). The
`tailscale_metrics_endpoint` (`just test-tailscale-metrics-timer`),
`os_apt_maintenance` (`just test-os-apt-maintenance-failed-run`) and
`metrics_endpoint` (`just molecule-test metrics_endpoint`) Molecule scenarios
run select and verify with `impl: python` against real systemd.
