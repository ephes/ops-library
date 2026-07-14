# Changelog

All notable changes to the ops-library collection will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- `marina_deploy` now excludes SQLite database and WAL/SHM runtime files from
  source rsync, preventing staging deploys from overwriting live Wagtail content
  with a controller-local `db.sqlite3`.
- `heis_deploy` now installs its host-side prerequisites and excludes SQLite
  database/WAL/SHM files from source rsync so code deploys preserve production
  content alongside the already-persistent media directory; page setup and
  content seeding can now be disabled independently for production, and
  optional canonical-host redirects support production alias domains.
  HTTP and TLS routers can now use separate host rules so an alias with pending
  DNS does not block ACME certificates for otherwise valid production names.

### Breaking Changes
- **Python 3.14+ required** - Dropped support for Python 3.8–3.13
  - Supports Python 3.14 (N-2 policy currently aligns with the latest stable release)
  - All roles and testing infrastructure now require Python 3.14+
  - Update your systems before upgrading to this version
- **ansible-core 2.20+ required** - Dropped support for Ansible 2.9-2.14
  - ansible-core 2.20 is the minimum version compatible with Python 3.14+
  - Update your Ansible installation before upgrading

### Added
- `heis_production_backup.py.j2`, a locked service-owned Echoport/FastDeploy
  runner for remote SQLite plus media backup and restore of a dedicated Heis
  production host. It uses exact immutable remote targets, bounded subprocesses,
  systemd restart watchdogs, short host-local backup snapshots, and automatic
  DB/media safety rollback for restores. Watchdogs remain armed until every
  service is proven active; restore runs migrations and requires an exact local
  HTTP 200 through Django's HTTPS proxy path before accepting the new data.
- `weeknotes_home_deploy` role to deploy daybook's `weeknotes.home` Django
  steering-comments service with PostgreSQL provisioning, uv-managed
  dependencies, systemd/gunicorn, Traefik routing, and a `/healthz` check.
- `weeknotes_home_deploy` can render a `WEEKNOTES_HOME_CAST_BASE_URL`
  environment setting so the service can link delivered drafts back to
  django-cast edit and preview pages.
- `daybook_sessions_deploy` role to validate a macOS `uv` runtime, install a
  pinned Daybook checkout, sync it with `uv`, install `trufflehog`, and run
  `daybook sessions ship` as a periodic launchd job using
  private-control-repo supplied MinIO credentials.
- `daybook_sessions_deploy` can skip git remote fetches for private,
  pre-staged Daybook checkouts while still checking out a pinned ref.
- `daybook_sessions_deploy` now supports user LaunchAgent installs for
  laptop-style macOS hosts that do not expose passwordless sudo or root SSH.
- `zfs_usb_replication` now persists drive-present success/failure separately
  from clean missing-drive skips, and `backup_metrics_endpoint` exposes stable
  policy-aware USB attempt, capacity, and protection-freshness health for alerting.
- `zfs_usb_replication` can now apply guarded pre-sync age retention to managed
  target-only snapshots while preserving every source-present common anchor and
  waiting for asynchronous ZFS frees before receiving new data.
- `delve_deploy` now installs an optional service-owned Discovery reviewed RSS
  collector oneshot/timer, passes bounded non-secret collector defaults including
  a 100-source run cap and 2-8 concurrency range, and documents the rollout
  boundary (no feed-pack seeding in the public role).
- `mail_relay_deploy` now supports
  `mail_relay_postgrey_whitelist_clients_extra` for managed postgrey whitelist
  entries in addition to the role defaults.
- `voxhelm_deploy` can now put transcription jobs into `remote_pull` mode with
  validated worker-token and shared S3 artifact settings, while
  `voxhelm_remote_worker_deploy` installs a pinned public-PyPI
  `voxhelm[diarization]` worker on macOS and runs it under launchd.
- `voxhelm_ingress_deploy` now blocks `/v1/internal` by default at the Traefik
  edge, with an explicit separate allowlist for deliberately private worker
  routes.
- `tailscale_metrics_endpoint` role to expose authenticated Tailscale login
  state and node-key expiry JSON for Nyxmon monitoring.
- `voxhelm_deploy` now supports production pyannote speaker diarization wiring,
  including optional `uv sync --extra diarization` installation, protected
  Hugging Face token env rendering, and validation when the backend is enabled.
- `nyxmon_storage_exporter` now caches successful ZFS pool samples and reuses them during quiet-hours pool skips, keeping capacity JSON paths stable for monitoring while marking cached values explicitly.
- `os_apt_maintenance` endpoint responses now expose `$.meta.state_reboot_required` so operators can inspect the reboot-required value from the durable state file separately from the live marker.
- `os_apt_maintenance` role for host-local apt update/dist-upgrade/autoremove/autoclean timers with durable JSON state and an optional authenticated Nyxmon endpoint.
- `wagtail_deploy` now supports a stable `wagtail_db_worker_id` and passes it to Django Tasks `db_worker --worker-id`, allowing each deployed site to run a distinct database-backed task worker
- `wagtail_deploy` now includes a `redirect-www` Traefik middleware that strips the `www.` prefix via regex redirect (302), applied unconditionally to the HTTPS router
- `headless_mode` role to persist hosts on a non-graphical systemd target and disable running display-manager services without requiring a reboot
- `paperless_deploy` can now promote existing Paperless users to active staff superusers during deploy via `paperless_existing_superusers`
- Takahe lifecycle roles: `takahe_shared`, `takahe_deploy`, `takahe_backup`, `takahe_restore`, and `takahe_remove` with systemd services, nginx caching/accel proxy, Traefik routing, and PostgreSQL provisioning
- Mastodon lifecycle roles: `mastodon_shared`, `mastodon_deploy`, `mastodon_backup`, `mastodon_restore`, `mastodon_maintenance`, and `mastodon_remove` with rbenv+nvm runtimes, systemd services, Traefik routing, and backup/restore tooling
- `open_webui_deploy` and `open_webui_remove` roles to run Open WebUI via Docker Compose with Traefik routing, persistent storage, and optional basic auth
- `open_webui_venv_deploy` and `open_webui_venv_remove` roles for a uv-managed venv deployment with systemd, Traefik routing, and persistent data
- `zfs_syncoid_replication` role for scheduled syncoid replication with alert hooks and optional spindown script
- `zfs_usb_replication` role for USB-attached ZFS replication with device detection and optional alerts
- `minio_offsite_replication` role to pull MinIO archives from a remote host into offsite storage via systemd timer, rsync/SSH, and alert hooks
- `mail_offsite_replication` role to pull maildir + staged DB/config artifacts from a remote host into offsite ZFS storage with post-sync snapshots, status markers, and alert hooks
- `encrypted_volume_prepare` role to verify, unlock, and mount LUKS data volumes with keyfile support, UUID validation, crypttab/fstab wiring, and a validate-only dry run
- `nyxmon_backup` role for SQLite-safe snapshots with metadata, manifests, and automatic archive fetches
- `nyxmon_restore` role with staging validation, safety snapshots, rollback support, and service verification
- `ollama_install` role to install and run Ollama on macOS via Homebrew with launchd management
- `ollama_remove` role to unload launchd, remove the plist, and optionally remove data/logs, service user, and Homebrew package
- `docker_install` role to install Docker Engine + Docker Compose v2 (plugin) on Ubuntu via the official Docker apt repository
- `shell_basics_deploy` role to install fish, modern CLI tools (btop, bmon, sysstat/iotop, tealdeer, eza), set shell/editor defaults, and keep chezmoi current via upstream installer
- `snappymail_deploy` role to install SnappyMail from upstream archives (PHP-FPM + nginx), wire IMAP/SMTP defaults, persist data under `/mnt/cryptdata/snappymail`, and expose via Traefik
- ReadTheDocs integration with Sphinx and MyST parser
  - Browsable documentation at https://ops-library.readthedocs.io/
  - Furo theme for modern, clean appearance
  - Automated role documentation from individual READMEs
  - Just commands for documentation workflow (docs-build, docs-watch, etc.)
  - Documentation validation script (validate_docs.py)
- Migrated to uv for Python dependency management
  - Faster dependency resolution and installation
  - Simplified justfile commands using `uv run`
  - Removed manual venv activation requirements
- `homeassistant_deploy`, `homeassistant_backup`, and `homeassistant_remove` roles to cover the full lifecycle alongside the existing restore workflow
- `homeassistant_restore` role to validate archives, create safety snapshots, restore files, and roll back on failure
- FastDeploy backup & restore workflow:
  - `fastdeploy_backup` role with metadata-rich snapshots, disk-space validation, and archive support
  - `fastdeploy_restore` role with safety snapshots, permission fixes, health-check retries, and rollback automation
- Paperless-ngx suite: `paperless_deploy`, `paperless_backup`, `paperless_restore`, `paperless_postgres`, and `paperless_remove` roles for deployment, disaster recovery, and safe removal
- `redis_install` role to provision standalone Redis instances with optional authentication, persistence, and memory tuning
- `postgres_install` role to install PostgreSQL with manageable config, databases, users, and extensions
- `minio_deploy` role to provision MinIO with dual-router Traefik exposure, security hardening, and optional client bootstrapping
- `minio_remove` role to destructively remove MinIO with confirmation, optional data preservation, and Traefik cleanup
- Dynamic DNS support in `dns_deploy`, adding an opt-in LiveDNS updater with dedicated service accounts, timers, and IPv4/IPv6 support
- UniFi lifecycle roles: `unifi_deploy`, `unifi_backup`, `unifi_restore`, and `unifi_remove` (Mongo-auth aware, Traefik/HA integration, Justfile wiring, docs)
- Navidrome lifecycle roles: `navidrome_deploy`, `navidrome_backup`, `navidrome_restore`, and `navidrome_remove` (systemd binary install, Traefik basic auth, rescan timer, backup/restore tooling)

### Changed
- `openclaw_deploy` now installs the official Codex app-server plugin at the
  OpenClaw-matching release and supports an
  explicit canonical `auth.order.openai` profile list so deployments can require
  ChatGPT/Codex subscription OAuth for OpenAI agent turns without silently
  falling back to API-key billing. Documentation examples now use upstream
  stable `v2026.6.11`.
- `mail_relay_deploy` now documents IPv4-only relay mode and exposes
  `mail_relay_smtp_address_preference` so deployments can avoid or de-prioritize
  IPv6 while PTR/forward DNS is not aligned for outbound delivery.
- `voxhelm_remote_worker_deploy` now defaults to `caffeinate -ims` so macOS
  remote workers stay awake during long jobs while allowing display sleep.
- `tailscale_metrics_endpoint` now defaults node-key expiry alerts to warning
  inside 3 days and critical inside 1 day.
- `zed` role scrub timers can optionally wait for completion and run a post-scrub spindown hook
- Unit tests for OpenClaw metrics collector canary behavior and schema invariants (`tests/unit/test_openclaw_metrics_collector.py`)

### Fixed
- `daybook_sessions_deploy` now uses an explicit boolean assertion for the S3
  session path check, keeping the role compatible with stricter Ansible
  conditional validation during real macOS deploys.
- `daybook_sessions_deploy` now runs the Daybook checkout update under a login
  shell for the service user, avoiding macOS sudo current-directory failures.
- `openclaw_deploy` synthetic canaries now use fresh per-attempt session ids
  derived from the configured canary prefix and clean up generated canary
  session files after a bounded retention window, preventing reused canary
  history from causing context overflow, malformed markers, and retry lock
  contention.
- `openclaw_deploy` metrics collector now treats parseable nonzero
  `health --json` output as collected health data, so transient Telegram probe
  failures do not set `collector_ok=false`.
- `nyxmon_storage_exporter` now parses in-progress and paused ZFS scrub
  timestamps without confusing the weekday `Mon` for a completed-scrub `on`
  marker, avoiding false scrub-age warnings while a pool is actively scrubbing.
- Deploy roles now build stat assertion labels and error messages from the
  original loop item instead of registered result invocation metadata,
  restoring compatibility with newer ansible-core controllers.
- Collection metadata now declares the documented ansible-core 2.20+ runtime
  requirement.
- `wagtail_deploy` rsync deployments now exclude the managed `.env` file and collected `/staticfiles` directory, preventing failed deploys from clobbering runtime secrets or deleting WhiteNoise assets before `collectstatic` runs.

### Changed
- `os_apt_maintenance` endpoint responses now derive `$.reboot_required` from the live `/var/run/reboot-required` marker so monitoring clears immediately after a successful reboot.
- `mastodon_backup` now excludes Mastodon's refetchable `public/system/cache` subtree from local media backups by default and records the media exclude list in backup manifests.
- `mastodon_backup` now runs `pg_dump` as the backup owner by default so password-authenticated dumps can write into root-owned backup directories.
- `openclaw_deploy` now uses a shallow single-tag/branch source checkout so upstream branch namespace conflicts do not block tag-pinned deployments.
- `openclaw_deploy` now renders the managed slash-skill session manifest without invalid inline Jinja comments.
- `openclaw_deploy` now normalizes legacy Telegram streaming aliases in persisted gateway configs before restarting newer OpenClaw releases.
- `openclaw_deploy` metrics collector now recognizes the current OpenClaw Telegram health shape (`running`/`connected`) when deriving `telegram_probe_ok`.
- `openclaw_deploy` documentation now uses upstream stable `v2026.6.10` in examples and validation hints.
- `paperless_deploy` now defaults to Paperless-ngx 2.20.15 and supports checksum verification for known upstream release archives.
- `paperless_deploy` now restarts Paperless services before health checks when a release symlink or package install changes, preventing upgraded deployments from leaving old worker processes serving the previous release.
- `homeassistant_deploy` now supports Home Assistant 2026.5 on Python 3.14, installs host-specific integration requirements before startup, removes legacy MET weather YAML when requested, and isolates the Matter Server in its own virtualenv to avoid Matter package namespace collisions.
- `unifi_deploy` now reconciles the Home Assistant UniFi admin when it already exists, including password hash drift and missing readonly site privileges.
- `dns_deploy` now supports Unbound cache prefetch, stale-TTL reset, optional RFC 8767 timeout tuning, recursion queue sizing, and disables Ubuntu's legacy resolvconf helper when the role manages `/etc/resolv.conf`
- `dns_deploy` blocklist refreshes now tolerate individual download failures, understand both hosts-style and AdGuard-style lists, and document the limits of `serve-expired` during WAN reconnects
- `netplan_config` now rejects interfaces that combine `dhcp4: true` with a manual IPv4 default route, documents DHCP-backed hosts to use DHCP-managed default routes, and offers an optional post-apply `networkctl reconfigure` recovery pass for `networkd` hosts stuck in a failed link state
- Closed out the refactor documentation pass so top-level docs and role READMEs
  describe the landed deploy/restore helper boundaries as complete work and
  frame remaining items as normal follow-up maintenance instead of pending
  refactor waves
- `dns_deploy` now exposes optional Unbound `serve-expired` controls and documents `forward_first` guidance for the root zone so resolver failover behavior is explicit
- `nyxmon_restore` now mirrors the Home Assistant structure (validate/prepare/restore/verify/cleanup), keeps cleanup in a top-level block/always flow, adds restore-phase block/rescue rollback, conditional restores, handler flush, and health checks
- `nyxmon_deploy` systemd service now launches Granian instead of Gunicorn to match the upstream project
- `ollama_install` stops any Homebrew-managed Ollama service by default, stops conflicting user-level `ollama serve` processes, and ensures the launchd service is running
- Updated README.md with prominent link to ReadTheDocs
- Updated repository URLs to https://github.com/ephes/ops-library
- Modernized Python tooling: uv replaces traditional pip/venv workflow
- Removed `docs-setup` command (auto-handled by uv)
- `fastdeploy_deploy` now depends on `postgres_install` for database provisioning (removing the legacy inline PostgreSQL tasks)
- `uv_install` detects alternate uv installations, relinks to newer binaries automatically, and enables `uv_update_existing` by default to keep hosts current
- `fastdeploy_deploy` implements Traefik's dual-router pattern with IP-based allow lists, bcrypt-hashed basic auth, security headers, and compression middleware
- Paperless roles now support Python 3.14 and include an optional ocrmypdf patch to keep OCR workflows unblocked
- `paperless_deploy` no longer installs `default-libmysqlclient-dev`, avoiding apt conflicts with MariaDB development packages on Ubuntu 24.04 when using the PostgreSQL backend
- `redis_install` enables config validation by default to catch syntax and runtime issues before service restarts
- `nyxmon_deploy` and `homelab_deploy` switch from Granian to Gunicorn and gained configurable Python version management (defaulting to 3.13)
- `nyxmon_deploy` now enforces the same dual-router authentication policy as other public services, including validation and hashed credentials
- `nyxmon_deploy` now flushes handlers and smoke-validates the live monitoring worker's OpsGate submit and approval URLs so stale approval-link wiring fails during deploy
- DNS deployment/removal flows hardened with improved resolver management, legacy `unbound_only` port detection, and safer variable validation
- `snappymail_deploy` now writes managed domain configs as `.json`, removes conflicting legacy `.ini` files, and supports `snappymail_remove_domains` cleanup for stale domain overrides
- `open_webui_deploy` documentation now calls out the `studio.tailde2ec.ts.net` hostname, Traefik config path/basic auth wiring, and ops-control preflight bypass flag
- `open_webui_remove` now defaults to non-destructive options and supports removing compose/env files separately from the site directory
- `zfs_usb_replication` gained optional syncoid identifiers, force-export, and spindown hooks to prevent snapshot collisions and park disks after USB runs
- `openclaw_deploy` synthetic canary collection now sets explicit collector `TimeoutStartSec=600`, keeps dedicated canary session-id routing, and preserves stable canary metadata keys (`agent`, `timeout_seconds`, `session_id`) in payload defaults

### Fixed
- `backup_metrics_endpoint` and `openclaw_deploy` collector timers now schedule from timer activation and collector completion, preventing post-reboot or post-restart `active (elapsed)` timers with no next run.
- `mail_spam_deploy` now configures the Rspamd APT repository with a scoped `signed-by` keyring and removes the legacy global apt-key entry, avoiding apt-key deprecation warnings on Ubuntu 24.04.
- `mastodon_backup` now restarts Mastodon services after failed backup payload capture, preventing `pg_dump` or media-copy failures from leaving services stopped.
- `mastodon_restore` now makes the staged database dump path traversable by the restore OS user before running `pg_restore`, while keeping the default peer-auth restore user.
- `wagtail_deploy` now protects the top-level `/cache` directory from rsync deletion and recreates `wagtail_cache_dir` after source deployment, preventing Django file-based cache failures like the python-podcast feed incident
- `mastodon_deploy` now resolves the concrete Node version path from `nvm version` instead of guessing an `nvm` directory name from `.nvmrc`, fixing deploys where values like `24.10` install under `v24.10.0` and otherwise break `yarn` during asset precompile
- `mastodon_deploy` now clears Rails cache after source, runtime, dependency, migration, or asset-build changes so stale cached instance metadata does not survive Mastodon upgrades in Redis after the services restart
- `mastodon_deploy` now restarts the web, Sidekiq, and streaming services when source, runtime, dependency, migration, or asset-build tasks change, so upgrades and recovery reruns do not leave long-running processes serving the previous release until a manual restart
- `logyard_vector_deploy` now disables the Vector Loki sink startup health check by default and validates staged config with `--skip-healthchecks`, preventing transient Logyard/Loki 5xx responses from blocking Vector service startup after package upgrades or restarts.
- `dns_deploy` now points its default AdGuard DNS filter source at the maintained upstream URL, avoiding daily blocklist refresh failures from the retired GitHub raw path
- `sanoid` now renders dataset `use_template` values using the bare template name expected by Sanoid instead of the literal section header, restoring per-dataset retention and pruning behavior for roles like Fractal Time Machine backups
- Home Assistant presence automations now include the default file to prevent missing automation imports after deployment
- `dns_remove` cleans up DDNS units reliably and no longer crashes on undefined variables during selective removal
- `unifi_restore` now re-imports MongoDB dumps, honors host/port overrides, and ships with sane defaults so UniFi logins and controller state survive a remove/deploy/restore cycle
- `unifi_deploy` gracefully skips the Home Assistant integration on the very first bootstrap when the UniFi “default” site does not exist yet, avoiding infinite waits on greenfield installs
- `open_webui_deploy` now validates the bind host and host port range to catch invalid settings earlier
- `zfs_usb_replication` now creates `/etc/exports.d` before mount and auto-sets `canmount=off` on existing recursive+readonly targets to avoid mountpoint creation failures on subsequent runs

## [2.0.0] - 2025-10-09

### Breaking Changes
- **REMOVED**: `python_app_systemd` role - Legacy manifest-driven deployment (use dedicated `*_deploy` roles instead)
- **REMOVED**: `python_app_django` role - Legacy manifest-driven Django deployment (use dedicated `*_deploy` roles instead)

### Added
- `homelab_deploy` role - Django/Granian deployment with dual router Traefik authentication
- `homelab_remove` role - Safe removal with data preservation options
- `traefik_deploy` role - Install and harden Traefik with Let's Encrypt automation, architecture auto-detection, and smoke tests
- `traefik_remove` role - Safe Traefik uninstallation with confirmation gates and preservation toggles
- `dns_deploy` and `dns_remove` roles - Manage Pi-hole/Unbound (later Unbound-only) DNS stacks with split-DNS views and clean removal
- Dual router authentication pattern for Traefik (internal: no auth, external: basic auth)
- Comprehensive Traefik security documentation
- Broken venv detection and auto-removal in Python deployment tasks
- Build ignore patterns in galaxy.yml for faster collection builds
- Comprehensive documentation structure with README.md and ARCHITECTURE.md
- CLAUDE.md for AI assistant context
- Standardized role README template

### Changed
- Streamlined role documentation for consistency
- Fixed systemd service template to remove `ProtectHome` for services in /home
- Improved validation.yml to handle undefined variables gracefully in homelab_remove
- Removed legacy role documentation pages
- Updated role index to reflect removal
- Added migration guidance for users of removed roles
- Updated uv_install examples to use modern deployment pattern
- `nyxmon_deploy` gained rsync support for additional source directories and smarter uv-based dependency management (pyproject validation, lock cleanup, mode-aware sync commands)

### Fixed
- Template evaluation crashes in homelab_remove when home directory doesn't exist
- Undefined variable errors in removal validation when database/media checks are skipped
- Permission issues with Python virtual environments on redeployment

### Migration Guide
If you were using `python_app_systemd` or `python_app_django`:
1. Migrate to dedicated roles: `fastdeploy_deploy`, `nyxmon_deploy`, `homelab_deploy`, etc.
2. Follow the role development guide to create custom deployment roles if needed
3. The old `services.d/` manifest workflow is no longer supported

## [1.0.0] - 2024-09-22

### Added
- Initial release of ops-library collection
- Core service deployment roles:
  - `fastdeploy_deploy` - Deploy FastDeploy platform
  - `nyxmon_deploy` - Deploy Nyxmon monitoring service
  - `fastdeploy_remove` - Remove FastDeploy service
  - `nyxmon_remove` - Remove Nyxmon service
- Service registration roles:
  - `apt_upgrade_register` - Register apt upgrade tasks with FastDeploy
  - `fastdeploy_register_service` - Generic service registration helper
  - `fastdeploy_self_deploy` - FastDeploy self-deployment registration
- Bootstrap roles:
  - `ansible_install` - Install Ansible and dependencies
  - `uv_install` - Install uv for Python environment management
  - `sops_dependencies` - Install SOPS/age prerequisites
- Testing infrastructure:
  - `test_dummy` - Example service for testing deployment patterns
- Legacy compatibility roles:
  - `python_app_django` - Django application deployment (deprecated)
  - `python_app_systemd` - Systemd service management (deprecated)

### Security
- Strict validation of secrets to prevent "CHANGEME" placeholder values
- SOPS/age encryption support for secrets management
- Sudoers configuration for privilege separation

## Role Version History

### fastdeploy_deploy
- **1.0.0** (2024-09-22): Initial release with rsync/git deployment support

### nyxmon_deploy
- **1.0.0** (2024-09-22): Initial release with Telegram integration

### apt_upgrade_register
- **1.0.0** (2024-09-22): Initial release with SSH key management

[Unreleased]: https://github.com/ephes/ops-library/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/ephes/ops-library/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/ephes/ops-library/releases/tag/v1.0.0
