# graphyard_deploy

Deploys the Graphyard production stack on Ubuntu/Debian hosts, including the
core Django runtime plus automation-owned InfluxDB and Grafana containers.

## What This Role Does

- Creates/maintains the `graphyard` user and app directories.
- Deploys Graphyard source via `rsync` (default) or `git`.
- Installs Docker Engine + Compose when the dependency runtime is enabled.
- Creates/owns the Graphyard Docker Compose runtime for:
  - `graphyard-influxdb`
  - `graphyard-grafana`
- Renders and enables `graphyard-runtime.service` to supervise the dependency runtime.
- Creates a uv-managed virtual environment and syncs runtime dependencies.
- Renders `/etc/graphyard/graphyard.env`.
- Runs `manage.py migrate` and `manage.py collectstatic --noinput`.
- Optionally renders and applies declarative `MetricCollectionSpec` definitions.
- Optionally enforces retention on the managed InfluxDB bucket through the local
  `graphyard-influxdb` container CLI.
- Renders and enables systemd units:
  - `graphyard-runtime.service`
  - `graphyard-web.service`
  - `graphyard-agent.service`
- Optionally installs a pinned release of the Rust agent `graphyard-agent` and
  selects it for `graphyard-agent.service` with a systemd drop-in (see
  [Agent implementation](#agent-implementation-python-or-rust)); the default is
  the Python agent.
- Verifies deploy health via `GET /v1/health` on localhost.

## Requirements

- Target host runs systemd.
- `uv_install` role is available in this collection.
- For `rsync` deploys, controller has local Graphyard source checkout.
- Secrets must be supplied by the caller (for example via SOPS in ops-control).

## Key Variables

| Variable | Default | Notes |
| --- | --- | --- |
| `graphyard_deploy_method` | `rsync` | `rsync` or `git` |
| `graphyard_source_path` | `""` | Required when using `rsync` |
| `graphyard_rsync_excludes` | see `defaults/main.yml` | rsync `--exclude` patterns for `rsync` mode |
| `graphyard_git_repo` | `https://github.com/ephes/graphyard.git` | Used for `git` deploy mode |
| `graphyard_git_version` | `main` | Branch/tag/commit for `git` mode |
| `graphyard_home` | `/opt/apps/graphyard` | Base path |
| `graphyard_site_path` | `{{ graphyard_home }}/site` | Project root on host |
| `graphyard_env_path` | `/etc/graphyard/graphyard.env` | Environment file consumed by systemd units |
| `graphyard_django_secret_key` | `CHANGEME` | Required, must be overridden |
| `graphyard_influx_token` | `CHANGEME` | Required when `graphyard_influx_token_required=true` |
| `graphyard_runtime_enabled` | `true` | Manage InfluxDB/Grafana via Docker Compose + systemd |
| `graphyard_runtime_service_name` | `graphyard-runtime` | Dependency runtime unit name |
| `graphyard_compose_path` | `{{ graphyard_home }}/docker-compose.yml` | Managed compose file path |
| `graphyard_docker_network_name` | `graphyard-monitoring` | Shared external Docker network used by Grafana, InfluxDB, and Logyard |
| `graphyard_influx_image` | `influxdb:2.7` | Production InfluxDB image |
| `graphyard_metric_collection_specs_apply` | `false` | Render/apply declarative metric specs via `manage.py apply_metric_collection_specs` |
| `graphyard_metric_collection_specs_prune` | `false` | Pass `--prune` so DB specs omitted from the rendered file are deleted by `name` |
| `graphyard_metric_collection_specs_path` | `/etc/graphyard/metric-collection-specs.json` | Rendered JSON file path for declarative specs |
| `graphyard_metric_collection_specs` | `[]` | Authoritative list of spec objects keyed by `name` |
| `graphyard_influx_retention_apply` | `false` | Inspect/update the existing InfluxDB bucket retention during deploy |
| `graphyard_influx_bucket_retention` | `0s` | Desired retention duration for `graphyard_influx_bucket` (for example `180d`) |
| `graphyard_influx_container_name` | `graphyard-influxdb` | Container used for `influx bucket list/update` |
| `graphyard_influx_data_dir` | `/var/lib/graphyard/influxdb2` | Persistent InfluxDB engine data path |
| `graphyard_influx_config_dir` | `/var/lib/graphyard/influxdb2-config` | Persistent InfluxDB config/init path |
| `graphyard_grafana_image` | `grafana/grafana-oss` | Production Grafana image |
| `graphyard_grafana_container_name` | `graphyard-grafana` | Stable Grafana container name |
| `graphyard_grafana_data_dir` | `/var/lib/graphyard/grafana` | Persistent Grafana data path |
| `graphyard_grafana_admin_password` | `CHANGEME` | Required when `graphyard_runtime_enabled=true`; used for first-boot Grafana init |
| `graphyard_grafana_influx_password` | `CHANGEME` | Required when `graphyard_runtime_enabled=true`; used for Grafana's InfluxDB v1 datasource auth |
| `graphyard_web_bind_host` | `127.0.0.1` | Web bind host |
| `graphyard_web_bind_port` | `8051` | Web bind port |
| `graphyard_web_workers` | `1` | Keep conservative for SQLite profile |
| `graphyard_healthcheck_enabled` | `true` | Enable post-deploy health verification |
| `graphyard_skip_django_manage` | `false` | Skip migrate/collectstatic in rollback workflows |
| `graphyard_agent_impl` | `python` | `python` or `rust`; see [Agent implementation](#agent-implementation-python-or-rust) |

See `defaults/main.yml` for the full variable set.

## Example

```yaml
- name: Deploy Graphyard core app
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.graphyard_deploy
      vars:
        graphyard_deploy_method: rsync
        graphyard_source_path: /Users/jochen/projects/graphyard
        graphyard_django_secret_key: "{{ graphyard_secrets.django_secret_key }}"
        graphyard_influx_token: "{{ graphyard_secrets.influx_token }}"
        graphyard_grafana_admin_password: "{{ graphyard_secrets.grafana_admin_password }}"
        graphyard_grafana_influx_password: "{{ graphyard_secrets.grafana_influx_password }}"
        graphyard_influx_retention_apply: true
        graphyard_influx_bucket_retention: 180d
        graphyard_django_allowed_hosts:
          - 127.0.0.1
          - localhost
          - graphyard.home.xn--wersdrfer-47a.de
        graphyard_django_csrf_trusted_origins:
          - https://graphyard.home.xn--wersdrfer-47a.de
        graphyard_grafana_base_url: https://grafana.home.xn--wersdrfer-47a.de
        graphyard_docker_network_name: graphyard-monitoring
        graphyard_metric_collection_specs_apply: true
        graphyard_metric_collection_specs_prune: true
        graphyard_metric_collection_specs:
          - name: Home Assistant Environment Scan
            enabled: true
            spec_type: home_assistant_env_scan
            interval_seconds: 60
            config:
              base_url: http://macmini.local:10020
              access_token: "{{ homeassistant_secrets.api_token }}"
              host_id: homeassistant
              service_id: homeassistant
```

## Notes

- This role now owns the Graphyard production dependency runtime as well as the
  app/systemd layer.
- Vector producer and Traefik ingress stay in separate roles:
  - `graphyard_vector_deploy`
  - `graphyard_ingress_deploy`
- The dependency runtime keeps the production container names, loopback ports,
  bind-mounted data paths, and shared `graphyard-monitoring` network stable so
  auth bootstrap, backups, Logyard, and ingress continue to work.
- When pre-existing manual dependency containers are found without the expected
  Compose labels, the role removes them and recreates them under the managed
  `graphyard-runtime.service` boundary.
- The current deploy helper boundary intentionally leaves `tasks/service.yml`
  inline. Graphyard renders and manages two distinct systemd units, and there
  is not yet a second caller that justifies a shared internal multi-unit helper.
- Auth/bootstrap reconciliation remains in `graphyard_auth_bootstrap_deploy`.
- Default `graphyard_rsync_excludes` also protect shared Logyard Grafana assets under
  `deploy/grafana/` so a Graphyard rsync deploy does not delete Logyard's dashboard or
  datasource provisioning files from the shared Grafana tree.
- The default `graphyard_rsync_excludes` entry `.git` has no trailing slash, so git
  metadata stays behind both for a normal clone, where `.git` is a directory, and
  for a git worktree, where it is a file. rsync never deletes excluded paths on the
  host, so a `.git` file that an earlier deploy copied to
  `{{ graphyard_site_path }}/.git` stays until it is removed by hand.
- Source changes from either `rsync` or `git` deploy mode notify both systemd services for restart,
  so updated Graphyard application code takes effect even when the unit files and env file are unchanged.
- Declarative metric spec provisioning is keyed by spec `name`.
- Default behavior is create/update only; omitted specs are left untouched unless `graphyard_metric_collection_specs_prune: true`.
- Prune is intentionally opt-in because it deletes any existing `MetricCollectionSpec` row whose `name` is not present in the rendered file.
- The underlying management command refuses `--prune` when the desired file is empty, which protects against accidental full deletion from a broken render.
- Retention enforcement updates the existing bucket in place; it does not create rollup buckets or
  rewrite Grafana to query alternate storage.
- On first boot against an empty InfluxDB state directory, the role also creates
  the Grafana-facing InfluxDB v1 auth expected by the provisioned InfluxQL
  datasource.

Rsync preserves `src/django/.env` alongside the runtime database and media.
A local developer environment file is never copied over the target configuration.
The role-managed runtime environment remains `/etc/graphyard/graphyard.env`.

### Optional inventory release comparison

Set `graphyard_inventory_releases_enabled: true` and supply
`graphyard_inventory_release_sources` to enable the weekly public release lookup.
The default is disabled. A source example is:

```yaml
graphyard_inventory_release_sources:
  - kind: pypi
    project: django
    targets:
      - kind: python
        name: django
```

Requires Graphyard's `refresh_inventory_releases` command and migration 0009.
The role validates the registry without fetching, installs root-owned configuration,
and enables `graphyard-inventory-releases.timer` (weekly, randomized by up to one
hour, persistent). Its oneshot uses the existing Graphyard user/environment and
writes only the Django directory within its filesystem sandbox. No host SSH,
Docker permission, new service credential or publisher change is needed. Public
metadata is fetched from fixed PyPI/GitHub/Homebrew HTTPS APIs; uploaded inventory
cannot choose URLs. Requests use no GitHub credentials and may hit public rate limits.

The receiver handles successful/failed lookup timestamps and compares only fresh
observations. Unknown sources, lookup failures, unsupported versions and stale
reports remain unknown. This reports available upstream releases, not upgrade
compatibility or vulnerability conclusions. Configuration is stored in
`{{ graphyard_env_dir }}/inventory-releases.json`. `--check` validates only;
`--force` requests an explicit refresh. The scheduled service always uses `--force`
so a recent manual refresh cannot cause a weekly run to skip and leave source
timestamps older than Graphyard's eight-day freshness limit. Direct management
commands without `--force` reuse successful cache entries younger than six days.
The private Django-directory lock serializes manual and scheduled refreshes and
is excluded from source rsync deletion. Deployment validates configuration only;
it does not trigger an upstream lookup.

To stop scheduling, set the enable flag false and redeploy; both timer and oneshot
are stopped/disabled. Cache history and the root-owned registry file are retained.
Application removal workflows must disable this optional job before deleting the
Graphyard runtime. For acceptance, start the service explicitly, inspect its exit
status and timer, verify the authenticated version view and database backup, then
repeat deployment and confirm no unnecessary refresh occurred.

Emergency `graphyard_skip_django_manage: true` also prevents enabling this job,
skips its management command validation, and stops an installed timer/service.
Check mode does not attempt to start units that have not yet been written.
The refresh lock basename is always protected by rsync, including when custom
excludes are supplied. The web and refresh units both use `graphyard_user`.
Boolean options are typed YAML/JSON booleans; use `-e '{"graphyard_inventory_releases_enabled":false}'`
when overriding a directly invoked role (the core orchestration play may set its
own explicit value).

### Optional inventory status monitoring

`graphyard_inventory_monitor_token` defaults to empty (machine access disabled).
Set a dedicated random secret containing 32-128 URL-safe characters
(`A-Z`, `a-z`, `0-9`, `_`, `-`) from private secret storage to render
`GRAPHYARD_INVENTORY_MONITOR_TOKEN` into the protected Django environment. Do not
reuse producer credentials or Django passwords. With a compatible Graphyard
receiver, monitoring can read `GET /v1/inventory/status` over HTTPS using Bearer
authentication or Basic username `inventory-monitor` and this secret as password.
This credential grants no ingest, UI-session or admin access. An external monitor
must check expected host/source identities and freshness, not only zero failures.
This role configures receiver access; check provisioning belongs to orchestration.

## Agent implementation (Python or Rust)

`graphyard-agent.service` runs either the Python agent from the venv
(`manage.py start_agent`, the default) or its Rust port `graphyard-agent`, a
single binary published as a GitHub release of graphyard (tag
`agent-rs-v<version>`, asset
`graphyard-agent-<version>-x86_64-unknown-linux-gnu.tar.gz`; the release build
needs no glibc symbol newer than 2.35, so Ubuntu 22.04 or newer runs it). Both
use the same database, `/etc/graphyard/graphyard.env`, user and working
directory; only one of them runs at a time. The contract is section 8.3 of
graphyard's `agent-rs/PLAN.md`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `graphyard_agent_impl` | `python` | `python` or `rust`: which agent the unit starts |
| `graphyard_agent_rust_version` | `""` | Release to install, e.g. `0.1.0`. Empty: nothing is installed, validated or pruned. Required for `rust` |
| `graphyard_agent_rust_sha256` | `""` | sha256 of the release archive (64 lowercase hex digits); required with a version unless a local archive is used |
| `graphyard_agent_rust_release_url` | GitHub release asset of `graphyard_agent_rust_version` | Download URL |
| `graphyard_agent_rust_local_archive` | `""` | Controller path of an archive with the release layout; replaces the download (development). Checked against `graphyard_agent_rust_sha256` when both are set |
| `graphyard_agent_rust_install_root` | `/opt/graphyard-agent` | Versions are installed to `<root>/<version>/graphyard-agent` |
| `graphyard_agent_rust_keep_versions` | `3` | Newest installed versions kept by pruning |

Set these in host variables, not in the play's role `vars:`, so the inventory
is the one place to switch. A pinned version is installed with either
implementation, which allows installing the binary ahead of the switch.

What the role does, in order:

1. Validates the settings before anything changes (`rust` needs a version; a
   version needs a checksum or a local archive; a checksum or local archive
   without a version is refused).
2. After the migrations (`django.yml`), with a version set and
   `<root>/<version>/` missing: downloads the archive with `get_url` and the
   pinned checksum (or copies the local archive and checks its checksum),
   refuses an archive that does not hold exactly the regular files
   `graphyard-agent` and `LICENSE` at its root (checked with `tar --list`
   before extraction; links and devices are refused), unpacks it into
   `<root>/.staging/`, records the archive checksum in
   `<root>/<version>/.archive-sha256` and moves the directory into place
   (root-owned, `0755`). An installed version is never modified: the same
   version from a different archive fails the run.
3. Runs, as `graphyard_user` by the versioned path and without the
   environment file (no secrets needed), `graphyard-agent --version` (must
   print `graphyard-agent <version> (<commit>)`) and
   `graphyard-agent --check-schema --db <django path>/db.sqlite3` (read-only).
   A failure stops the play; a version installed in this run is removed
   again, the drop-in, the running unit and the other versions stay as they
   were.
4. Writes `/etc/systemd/system/graphyard-agent.service.d/agent-impl.conf` for
   `rust` and removes it for `python`:

   ```ini
   [Service]
   ExecStart=
   ExecStart=/opt/graphyard-agent/<version>/graphyard-agent --db /opt/apps/graphyard/site/src/django/db.sqlite3
   ```

   The base unit is unchanged: its Python `ExecStart`, `User`,
   `EnvironmentFile`, `WorkingDirectory` and `Requires=graphyard-runtime.service`
   apply to both implementations. The version is part of the drop-in, so a
   version change or a switch changes the file, reloads systemd and restarts
   the agent (`restart graphyard agent`); a deploy that changes neither
   restarts nothing on its account.
5. After the handlers ran: waits up to 30 s until the unit is active and its
   main process is the selected agent: for `rust`, `readlink /proc/<pid>/exe`
   equals the versioned binary; for `python`, the argv in `/proc/<pid>/cmdline`
   is `<venv>/bin/python manage.py start_agent` and the executable is not
   below the install root. Not in check mode.
6. Only then, with a version set: prunes version directories beyond the
   newest `graphyard_agent_rust_keep_versions` (by modification time). The
   pinned version, the version the live process runs and the previously
   selected one (`<root>/.previous-version`, written when the selection moves
   away from a Rust version) are always kept; directories that are not
   version-shaped are never touched.

The Python venv keeps being built and updated for both implementations: the
web app needs it and it is the rollback path.

Example (host variables):

```yaml
# Install 0.1.0 next to the running Python agent, nothing switched
graphyard_agent_impl: python
graphyard_agent_rust_version: "0.1.0"
graphyard_agent_rust_sha256: "<sha256 from the release's .sha256 asset>"

# Switch: the next deploy writes the drop-in and restarts graphyard-agent
graphyard_agent_impl: rust
```

Development build instead of a release (archive with the release layout):

```yaml
graphyard_agent_impl: rust
graphyard_agent_rust_version: "0.1.0"
graphyard_agent_rust_local_archive: /path/to/graphyard-agent-0.1.0-x86_64-unknown-linux-gnu.tar.gz
```

The default `graphyard_rsync_excludes` contain `agent-rs/target/`, so an
`rsync` deploy from a local checkout never ships the Cargo build output of the
Rust port.

### Rollback

- Back to Python: set `graphyard_agent_impl: python` and deploy. The drop-in
  is removed and the unit restarts with the venv `manage.py start_agent` on
  the same database; nothing in the database or InfluxDB depends on which
  agent wrote it. The binary stays installed, so switching forward again
  needs no download.
- Emergency without Ansible, on the host:
  `rm /etc/systemd/system/graphyard-agent.service.d/agent-impl.conf && systemctl daemon-reload && systemctl restart graphyard-agent`.
  Set `graphyard_agent_impl: python` in the inventory before the next deploy,
  or that deploy writes the drop-in again.
- Bad Rust release: pin the previous `graphyard_agent_rust_version` and
  `graphyard_agent_rust_sha256` again and deploy. Its directory is still
  installed (pruning keeps the previously selected version), the drop-in
  changes and the unit restarts.

## Restart behavior

Source and dependency changes notify the existing restart handlers after deployment.
Graphyard restarts both its web and agent services. Unchanged syncs do not request a restart.

Set `graphyard_ca_store_root` to the prepared per-container CA root to mount
replacement native trust stores; prepare with `container_ca_remediate` before
deploying and refresh after image/custom CA changes. The empty default leaves
image trust unchanged. Verify actual runtime TLS before claiming protection.
