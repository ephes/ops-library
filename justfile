# ops-library Justfile
# Testing and development automation for Ansible collection

# Default - show available commands
default:
    @just --list

# Setup development environment with pre-commit hooks
setup:
    @echo "Setting up development environment..."
    @./setup-pre-commit.sh

# Run the default contributor validation path
test: venv test-rustup-security test-ca-trust-consumers test-voxhelm-trust-refresh test-container-ca-activate test-chrome-ca-distrust test-container-ca-remediate test-macos-python-ca-remediate test-linuxserver-ca-remediate test-macos-ca-remediate test-security-trust-remediate test-aws-ca-bundle test-python-security-floor test-homeassistant-uv-system-certs test-root-downloads test-lowfindings test-mail-monitoring-probe test-docker-cache-cleanup test-time-sync-check test-paperless-search-index test-daybook-operations test-macos-ssh-tunnel test-macos-java-trust test-macos-smb-mount-keeper typecheck test-roles test-zfs-snapshot-file-attestation test-zfs-usb-replication test-software-live test-software-live-impl test-software-live-rust-fixtures test-software-estate test-debian13-compatibility test-os-apt-maintenance-refresh test-traefik-transactions test-openclaw-gateway-config test-openclaw-audio-transcription test-openclaw-codex-registration-backport test-openclaw-doctor-activation test-openclaw-compose-lifecycle test-openclaw-heartbeat-recovery test-network-recovery test-monitoring-pipeline-repair test-traefik-metrics-entrypoint test-os-apt-maintenance-failed-run test-tailscale-metrics-timer test-nyxmon-deploy test-mailgun-relay-deploy test-graphyard-deploy-agent test-rsync-git-excludes test-deploy-restart-notifications test-certbot-dns-renewal-hooks test-certbot-dns-rfc2136 test-ddns-update test-ssh-forwarding-roles test-ssh-forwarding-integration test-vaultwarden-maintenance test-bind-authoritative-secondary test-bind-authoritative-dynamic test-dns-metrics-endpoint test-daybook-sessions-deploy test-daybook-photos-offload-deploy test-daybook-photos-offload-symlink-safety test-daybook-photos-archive-sync-deploy test-daybook-voice-memo-inbox-deploy test-daybook-voice-memo-work test-daybook-mail-work test-daybook-voice-memo-attention test-daybook-weeknotes-identity-ops test-daybook-weeknotes-reconcile-check-mode test-weeknotes-home-deploy test-work-app-deploy test-opaq-app-deploy test-homelab-lifecycle-safety test-heis-production-backup test-fastdeploy-backup-key test-fastdeploy-retired-restore test-echoport-remote-command-guard test-metrics-httpd-fixtures test-python-podcast-production-db-backup test-postfixadmin-echoport-backup test-mail-db-echoport-backup test-django-chat-staging-db-backup test-takahe-deploy test-gotosocial-deploy test-gotosocial-echoport-backup test-mastodon-slim test-mastodon-nginx test-mastodon-traefik test-wagtail-deploy test-static-site-deploy test-voxhelm-csrf test-voxhelm-parakeet test-secret-file-modes test-unifi-traefik-allowlist test-paperless-backup-exposure test-fetched-backup-archive-modes test-backup-archive-modes test-secret-no-log test-task-credentials test-become-environment-secrets test-shell-pipefail test-backup-service-restart test-graphyard-auth-bootstrap-changed-when test-metube-uv-sync-changed-when test-ansible-core-floor test-logyard-ingress test-delve-recorder-flags test-server-ad-analysis test-molecule-run-isolation test-restore-safety test-fastdeploy-service-token-settings test-fastdeploy-runner-step-states test-voxhelm-prune-and-service-knobs test-traefik-frame-options test-traefik-hsts test-traefik-logrotate test-traefik-backup-dynamic test-minio-backup-accounts test-echoport-sqlite-backup test-encrypted-volume-fstab test-minio-metadata-backup test-ssh-authorized-keys-manage test-opsgate-deploy-keys test-opsgate-rsync-excludes test-opsgate-deploy-impl test-collection-build-ignore test-rust-release-binary test-metrics-httpd-switch lint docs-build docs-lint
    @echo ""
    @echo "✅ Validation completed!"

# Run the strict validation gate
validate-strict: venv test-roles lint-strict docs-build docs-lint
    @echo ""
    @echo "✅ Strict validation completed!"

# Test all roles
test-roles: venv
    @echo "Testing all roles..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ./test_roles.py --all

test-network-recovery: venv
    @echo "Testing network recovery and Tailscale health templates..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_network_recovery

test-openclaw-gateway-config: venv
    @echo "Testing OpenClaw gateway config and model policy..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run pytest tests/unit/test_openclaw_gateway_config.py -q

test-openclaw-audio-transcription: venv
    @echo "Testing OpenClaw audio transcription configuration..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.unit.test_openclaw_audio_transcription

test-openclaw-codex-registration-backport: venv
    @echo "Testing the OpenClaw Codex process-registration backport..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run pytest -q tests/unit/test_openclaw_codex_registration_backport.py

test-openclaw-doctor-activation: venv
    @echo "Testing OpenClaw Doctor activation before role CLI tasks..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run pytest -q tests/unit/test_openclaw_doctor_activation.py tests/unit/test_openclaw_plugins.py

test-openclaw-compose-lifecycle: venv
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just _export-docker-host)"
    echo "Testing OpenClaw service restart bridge retention against real Docker Compose..."
    UV_PROJECT_ENVIRONMENT=.venv uv run pytest -q tests/integration/test_openclaw_compose_lifecycle.py

test-zfs-snapshot-file-attestation: venv
    @echo "Testing read-only ZFS snapshot-file attestation..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run pytest -q tests/unit/test_zfs_snapshot_file_attestation.py

test-zfs-usb-replication: venv
    @echo "Testing USB offsite rotation, anchors, retention and health state..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run pytest -q tests/unit/test_zfs_usb_replication_script.py tests/unit/test_zfs_usb_bookmark_anchors.py tests/unit/test_zfs_usb_snapshot_retention.py tests/unit/test_usb_replication_health.py

# Test a specific role
test-role ROLE: venv
    @echo "Testing role: {{ROLE}}"
    @UV_PROJECT_ENVIRONMENT=.venv uv run ./test_roles.py {{ROLE}}

test-monitoring-pipeline-repair: venv
    @echo "Testing apt-maintenance state permissions and Tailscale collector timer arming..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_monitoring_pipeline_repair

test-traefik-metrics-entrypoint: venv
    @echo "Testing that Traefik never opens an implicit :8080 metrics entrypoint..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_traefik_metrics_entrypoint

test-debian13-compatibility: venv
    @echo "Testing Debian 13 package and repository compatibility contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_debian13_compatibility

# Executes the rendered refresh runner against a fake apt-get: proves the
# index-only mode installs nothing and never stamps the maintenance state file.
test-os-apt-maintenance-refresh: venv
    @echo "Testing index-only apt refresh contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_os_apt_maintenance_refresh

# Drives a real failing apt run and asserts the state file stays readable for
# the endpoint group, so a failed run reports itself instead of serving 503.
test-os-apt-maintenance-failed-run: venv
    @echo "Testing that a failed apt-maintenance run still serves its state..."
    @just molecule-test os_apt_maintenance

# Reproduces a parked `active (elapsed)` collector timer and asserts the role
# detects it, refuses to accept it, and re-arms it once it can.
test-tailscale-metrics-timer: venv
    @echo "Testing Tailscale metrics collector timer arming against real systemd..."
    @just molecule-test tailscale_metrics_endpoint

test-nyxmon-deploy: venv
    @echo "Testing Nyxmon rsync safety and notification policy contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_nyxmon_deploy
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_nyxmon_lifecycle

# Builds the collection into a temp dir (rust/PLAN-foundation.md section 5).
# galaxy.yml build_ignore keeps rust/ and .github/ out of the collection archive
test-collection-build-ignore: venv
    @echo "Testing that the collection archive packs neither rust/ nor .github/..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_collection_build_ignore

# Static checks, filter unit tests and ansible-playbook runs against localhost
# with fake release archives (macOS needs Homebrew coreutils for GNU mv).
test-rust-release-binary: venv
    @echo "Testing rust_release_binary install, pin and prune (including the fail-closed prune cases)..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_rust_release_binary

# The metrics-httpd implementation switch (rust/metrics-httpd/PLAN.md 7.2/7.3):
# filter unit tests, consumer argv/drop-in/unit renders against goldens and
# ansible-playbook runs of select/verify against localhost with fakes
# (logyard_deploy and static_site_deploy in their own module).
test-metrics-httpd-switch: venv
    @echo "Testing metrics_httpd_switch and its consumer roles (drop-in, check-config, verify, pins)..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_metrics_httpd_switch tests.test_metrics_httpd_switch_logyard_static

# Needs cargo and cargo-deny 0.20.2 (rust/README.md); run it from a worktree.
# Not part of `just test`, which works without a Rust toolchain.
# Rust workspace: the checks of the `rust` CI job (fmt, clippy, tests, deny, scripts)
rust-check:
    #!/usr/bin/env bash
    set -euo pipefail
    cd rust
    # Package names only (validated by the script), word-split on purpose.
    excludes=$(cargo metadata --format-version 1 --no-deps --locked | python3 -I scripts/ci_excludes.py)
    cargo fmt --check
    cargo clippy --workspace $excludes --all-targets --locked -- -D warnings
    cargo test --workspace $excludes --locked
    cargo deny --locked check
    python3 -I -m unittest discover -s scripts -p 'test_*.py'

# Rust workspace tests only (cargo test and the rust/scripts tests).
rust-test:
    #!/usr/bin/env bash
    set -euo pipefail
    cd rust
    excludes=$(cargo metadata --format-version 1 --no-deps --locked | python3 -I scripts/ci_excludes.py)
    cargo test --workspace $excludes --locked
    python3 -I -m unittest discover -s scripts -p 'test_*.py'

# Parity harness of the Rust metrics-httpd port (rust/metrics-httpd/PLAN.md
# 8.3): builds the binary, runs it side by side with the rendered Python
# endpoint scripts under CPython 3.12 (the hosts' version; needs htpasswd),
# then the shadow comparer's tests under 3.12 and 3.13. Needs cargo; not part
# of `just test`. The `rust` CI job runs the same.
rust-parity-metrics-httpd: venv
    #!/usr/bin/env bash
    set -euo pipefail
    (cd rust && cargo build --locked -p metrics-httpd)
    python=$(uv run --python 3.12 --no-project python -c 'import sys; print(sys.executable)')
    UV_PROJECT_ENVIRONMENT=.venv uv run python rust/metrics-httpd/parity/run_parity.py \
        --binary rust/target/debug/metrics-httpd --python "$python"
    cd rust/metrics-httpd
    uv run --python 3.12 --no-project python -I -m unittest discover -s parity -p 'test_*.py'
    uv run --python 3.13 --no-project python -I -m unittest discover -s parity -p 'test_*.py'

test-mailgun-relay-deploy: venv
    @echo "Testing the mailgun-relay rsync excludes and the Python/Rust implementation switch..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_mailgun_relay_deploy

test-rsync-git-excludes: venv
    @echo "Testing that rsync deploys keep git metadata (worktree .git files too) off the host..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_rsync_git_excludes

# Python service from the public repo plus fake Rust release archives in a
# systemd container: switch, version change, refusals, rollback (downloads uv's
# Python 3.14 and the relay's dependencies).
test-mailgun-relay-deploy-molecule: venv
    @just molecule-test mailgun_relay_deploy

test-graphyard-deploy-agent: venv
    @echo "Testing the graphyard agent Python/Rust switch and the agent-rs/target rsync exclude..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_graphyard_deploy_agent

# Graphyard core from the public repo (dependency runtime off) plus fake Rust
# agent release archives in a systemd container: install next to Python,
# switch, version change and pruning, refusals, rollback (downloads uv's
# Python 3.12 and Graphyard's dependencies).
test-graphyard-deploy-molecule: venv
    @just molecule-test graphyard_deploy

test-deploy-restart-notifications: venv
    @echo "Testing that app deploy roles restart after source and dependency changes..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_deploy_restart_notifications

test-ddns-update: venv
    @echo "Testing the DDNS updater backends, failure exit codes and status file..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_ddns_update

test-certbot-dns-rfc2136: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_certbot_dns_rfc2136

test-certbot-dns-renewal-hooks: venv
    @echo "Testing Certbot DNS renewal hook rendering and failure aggregation..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_certbot_dns_renewal_hooks

test-ssh-forwarding-roles: venv
    @echo "Testing restricted SSH forwarding roles..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_ssh_forwarding_roles

test-ssh-forwarding-integration: venv
    @echo "Testing restricted forwarding against an isolated real sshd..."
    @just molecule-test ssh_restricted_forwarding_account

test-vaultwarden-maintenance: venv
    @echo "Testing Vaultwarden maintenance switch and package pinning contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_vaultwarden_maintenance

# Static checks: restore roles validate first, stop fail-closed, take a safety
# copy before overwriting and roll back in rescue.
test-restore-safety: venv
    @echo "Testing restore safety contracts (safety copy, fail-closed stop, rollback)..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_vaultwarden_restore_safety tests.test_fedi_restore_safety tests.test_file_restore_safety tests.test_restore_archive_members

# Uses a private work directory so parallel runs from other checkouts do not
# delete each other's rendered files.
test-bind-authoritative-secondary: venv
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Testing BIND transfer-backed (secondary) zone support..."
    work_dir=$(mktemp -d "${TMPDIR:-/tmp}/test-bind-authoritative-secondary.XXXXXX")
    trap 'rm -rf -- "$work_dir"' EXIT
    UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local -e "test_tmp_dir=$work_dir" tests/test_bind_authoritative_secondary.yml

test-bind-authoritative-dynamic: venv
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Testing BIND dynamic (RFC 2136) zone support..."
    work_dir=$(mktemp -d "${TMPDIR:-/tmp}/test-bind-authoritative-dynamic.XXXXXX")
    trap 'rm -rf -- "$work_dir"' EXIT
    UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local -e "test_tmp_dir=$work_dir" tests/test_bind_authoritative_dynamic.yml

test-dns-metrics-endpoint: venv
    @echo "Testing DNS metrics endpoint validation and collector behaviour..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_dns_metrics_endpoint.yml

test-daybook-sessions-deploy: venv
    @echo "Testing Daybook sessions deploy behavior..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_daybook_sessions_deploy.yml
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_daybook_sessions_follow_branch.yml
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_daybook_sessions_retire tests.test_daybook_sessions_become

test-daybook-photos-offload-deploy: venv
    @echo "Testing Daybook Photos offload deploy contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_daybook_photos_offload_deploy

test-daybook-photos-offload-symlink-safety: venv
    @echo "Testing Daybook Photos environment link safety..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_daybook_photos_offload_symlink_safety.yml

test-daybook-photos-archive-sync-deploy: venv
    @echo "Testing Daybook Nikon archive deployment contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run pytest tests/test_daybook_photos_archive_sync_deploy.py

test-daybook-voice-memo-inbox-deploy: venv
    @echo "Testing Daybook Voice Memo inbox deploy contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_daybook_voice_memo_inbox_deploy

test-daybook-voice-memo-work: venv
    @echo "Testing Daybook Voice Memo capable-work scheduler and source identity..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_daybook_voice_memo_work_deploy tests.test_daybook_work_source_access tests.test_daybook_catalog_access

test-daybook-mail-work: venv
    @echo "Testing Daybook mail work capability-host scheduler..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_daybook_mail_work_deploy

test-daybook-voice-memo-attention: venv
    @echo "Testing disabled Daybook attention deployment and restricted notifier contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_daybook_voice_memo_attention_deploy tests.test_daybook_voice_memo_attention_notifier_deploy tests.test_daybook_voice_memo_attention_reader

test-daybook-weeknotes-reconcile-check-mode: venv
    @echo "Testing configured and unconfigured Daybook reconcile check mode..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_daybook_weeknotes_reconcile_check_mode.yml --check

test-daybook-weeknotes-identity-ops: venv
    @echo "Testing crash-safe Daybook identity helper behavior..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_weeknotes_identity_ops

test-weeknotes-home-deploy: venv
    @echo "Testing weeknotes.home deployment templates and ingress validation..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_weeknotes_home_deploy.yml
    @ANSIBLE_COLLECTIONS_PATH="$(scripts/checkout-collections-path.sh)" UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_weeknotes_home_auth_check_mode.yml --check

test-heis-production-backup: venv
    @echo "Testing Heis production backup safety contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_heis_production_backup

# Forced-command allowlist for the Echoport remote runners' root SSH key: guard
# rules, plus every command each remote runner template really sends, plus the
# Rust port's decision fixtures (GUARD_SHA256, drift, prefilter contract), plus
# the role's impl selector and confirm_live.yml (localhost ansible-playbook runs).
test-echoport-remote-command-guard: venv
    @echo "Testing the Echoport remote command guard..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_echoport_remote_command_guard tests.test_echoport_command_guard_fixtures tests.test_echoport_remote_command_guard_role

# The guard role's molecule scenarios (rust/echoport-command-guard/PLAN.md 6.2):
# impl python, shadow and rust on Ubuntu 24.04 and Debian 13 against a real
# sshd (shadow and rust build the guard from this checkout in Docker), and the
# pin/prune scenario with stub releases. Needs Docker; not part of `just test`.
test-echoport-remote-command-guard-molecule:
    @just molecule-test-scenario echoport_remote_command_guard default
    @just molecule-test-scenario echoport_remote_command_guard shadow
    @just molecule-test-scenario echoport_remote_command_guard rust
    @just molecule-test-scenario echoport_remote_command_guard pins

# Regenerate the Rust guard port's Layer-1 fixtures from the Python guard
# (rust/echoport-command-guard/PLAN.md 7.2): record the test policies and the
# runners' commands in the repo venv, generate under Python 3.12 (production),
# and require identical output under 3.13 (staging) and the venv.
echoport-command-guard-fixtures: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python rust/echoport-command-guard/parity/gen_fixtures.py record
    @uv run --python 3.12 --no-project python -I rust/echoport-command-guard/parity/gen_fixtures.py generate
    @uv run --python 3.13 --no-project python -I rust/echoport-command-guard/parity/gen_fixtures.py check
    @UV_PROJECT_ENVIRONMENT=.venv uv run python rust/echoport-command-guard/parity/gen_fixtures.py check --record

# Fixtures of the Rust metrics-httpd port (rust/metrics-httpd/PLAN.md 8.2): they
# must regenerate byte for byte from the rendered Python endpoint scripts, the
# real htpasswd and CPython; differences to Rust must name a PLAN.md D item.
test-metrics-httpd-fixtures: venv
    @echo "Testing that the metrics-httpd fixtures match the Python endpoints..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_metrics_httpd_fixtures

# Regenerate the metrics-httpd fixtures in the repo venv (rendered templates,
# real htpasswd), then require identical stdlib families (JSON, float repr,
# meta) under CPython 3.12 (production hosts) and 3.13 (staging).
metrics-httpd-fixtures: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python rust/metrics-httpd/fixtures/generate.py write
    @uv run --python 3.12 --no-project python -I rust/metrics-httpd/fixtures/generate.py check --stdlib-only
    @uv run --python 3.13 --no-project python -I rust/metrics-httpd/fixtures/generate.py check --stdlib-only

# Layer 2 of the Rust echoport-command-guard (rust/echoport-command-guard/PLAN.md
# 7.5): realpath, lstat and user lookups, then the decisions (Python's check()
# against `--decide`), of the Rust guard against Python 3.12 (Ubuntu 24.04)
# and 3.13 (Debian 13), as root on real trees in containers. Needs Docker.
echoport-command-guard-layer2:
    @rust/echoport-command-guard/parity/e2e/run-layer2.sh

# Layer 3 of the Rust echoport-command-guard (PLAN.md 7.6): the Python, Rust
# and shadow forced commands end to end through sshd in Ubuntu 24.04 and
# Debian 13 containers, compared. Needs Docker.
echoport-command-guard-layer3:
    @rust/echoport-command-guard/parity/e2e/run-layer3.sh

# Lean measurements of the Rust echoport-command-guard (PLAN.md 8.3): the Rust
# and the Python guard in the Layer-3 containers, median of 20 runs, against
# the budgets. Needs Docker; the recorded numbers come from the x86_64 runner
# of the `rust` workflow started by hand (`gh workflow run rust.yml`).
echoport-command-guard-lean:
    @rust/echoport-command-guard/parity/e2e/run-lean.sh

# Fuzz the Rust echoport-command-guard (PLAN.md 7.4): the four cargo-fuzz
# targets for an hour each (or `seconds`), in containers with a pinned
# nightly. Needs Docker; updates rust/echoport-command-guard/fuzz/corpus/.
echoport-command-guard-fuzz seconds="3600":
    @rust/echoport-command-guard/fuzz/run-fuzz.sh {{seconds}}

# A FastDeploy restore must not bring back what the privilege reduction retired
# (services, sudoers files, rules with more than one narrow script).
test-fastdeploy-retired-restore: venv
    @echo "Testing that FastDeploy restores skip retired entries and broad sudo rules..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_fastdeploy_retired_restore

test-fastdeploy-backup-key: venv
    @echo "Testing FastDeploy backup object keys..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_fastdeploy_backup_key

test-python-podcast-production-db-backup: venv
    @echo "Testing python-podcast private media backup/restore contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_python_podcast_production_db_backup

test-postfixadmin-echoport-backup: venv
    @echo "Testing the fail-closed Echoport PostfixAdmin runner..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_postfixadmin_echoport_backup

test-mail-db-echoport-backup: venv
    @echo "Testing the Echoport mail database runner..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_mail_db_echoport_backup

test-django-chat-staging-db-backup: venv
    @echo "Testing the Echoport Django Chat staging database runner..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_django_chat_staging_db_backup

test-mastodon-slim: venv
    @echo "Testing Mastodon sizing validation, maintenance guards and backup pruning..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_mastodon_slim.yml

# Static contracts of gotosocial_deploy (validation, rendered config/route/unit).
test-gotosocial-deploy: venv
    @echo "Testing GoToSocial deploy validation and templates..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_gotosocial_deploy.yml

# Echoport GoToSocial runner: online backup, verified restore, rollback.
test-gotosocial-echoport-backup: venv
    @echo "Testing the Echoport GoToSocial runner..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_gotosocial_echoport_backup

# Full install of the pinned release in a systemd container (downloads ~40 MB).
test-gotosocial-molecule: venv
    @just molecule-test gotosocial_deploy

test-takahe-deploy: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_takahe_routing
    @echo "Testing Takahe error mail validation and env rendering..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_takahe_deploy.yml

test-work-app-deploy: venv
    @echo "Testing work app deployment templates, dual router config and validation..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_work_app_deploy.yml

test-homelab-lifecycle-safety: venv
    @echo "Testing homelab backup/restore/remove safety guards..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_homelab_lifecycle_safety.yml

test-mastodon-nginx: venv
    @echo "Testing the Mastodon nginx federation cache, timing log and file limit..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_mastodon_nginx

test-mastodon-traefik: venv
    @echo "Testing the Mastodon LOCAL_DOMAIN discovery route..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_mastodon_traefik

test-wagtail-deploy: venv
    @echo "Testing Wagtail env rendering and the secret validation switches..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_wagtail_deploy.yml
    @echo "Testing that the Wagtail dependency sync leaves out the dev group..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run pytest -q tests/test_wagtail_uv_sync.py

test-fastdeploy-service-token-settings: venv
    @echo "Testing FastDeploy service token env settings and their validation..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_fastdeploy_service_token_settings.yml
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_fastdeploy_token_helpers

test-fastdeploy-runner-step-states: venv
    @echo "Testing FastDeploy runner step states and advisory verification..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_fastdeploy_runner_step_states

# Quick syntax check for everything
syntax-check: venv
    @echo "Running quick syntax check..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ./test_roles.py --all | grep -E "(Testing role:|YAML Syntax|✓ PASSED|✗ FAILED)" || true

# Run ansible-lint summary (non-failing convenience helper)
lint: venv
    @echo "Running ansible-lint..."
    @echo "Note: this is a summary-only helper. Use 'just lint-strict' or 'just validate-strict' for a failing validation gate."
    @echo "Linting roles..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-lint roles/ 2>&1 | tail -3 || true

# Static check: tasks that send credentials over HTTP (uri headers, url_password,
# curl -H Authorization) must set no_log: true so -vvv output cannot print them.
test-minio-backup-accounts: venv
    @echo "Testing per-target MinIO backup accounts and stdin-only mc aliases..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_minio_backup_accounts

test-ssh-authorized-keys-manage: venv
    @echo "Testing ssh_authorized_keys_manage full-file and non-exclusive modes..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_ssh_authorized_keys_manage

test-opsgate-deploy-keys: venv
    @echo "Testing opsgate_deploy per-repository GitHub deploy keys..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_opsgate_deploy_keys

test-opsgate-rsync-excludes: venv
    @echo "Testing that the opsgate_deploy source sync leaves rust/ out of the Python app dirs..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_opsgate_rsync_excludes

test-opsgate-deploy-impl: venv
    @echo "Testing the opsgate_deploy Python/Rust switch (install, plists, verify, prune)..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_opsgate_deploy_impl

test-echoport-sqlite-backup: venv
    @echo "Testing the SQLite backups of the Echoport runners and backup roles under a write lock..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_echoport_sqlite_backup tests.test_sqlite_backup_runners

test-encrypted-volume-fstab: venv
    @echo "Testing that the encrypted volume fstab entry is stable (no rewrite, no remount)..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_encrypted_volume_fstab

test-secret-no-log: venv
    @echo "Checking that uri/command tasks carrying credentials or secret variables set no_log..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_secret_no_log tests.test_secret_exposure

# Run strict ansible-lint (fails on any finding not listed in .ansible-lint-ignore)
# plus the no_log check for credential-carrying tasks
lint-strict: venv test-root-downloads test-secret-no-log
    @echo "Running ansible-lint (strict mode)..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-lint roles/

# Run ansible-lint on a specific role
lint-role ROLE: venv
    @echo "Linting role: {{ROLE}}"
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-lint roles/{{ROLE}}

# Run pre-commit on all files
pre-commit: venv
    @echo "Running pre-commit on all files..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run pre-commit run --all-files

# Update pre-commit hooks to latest versions
pre-commit-update: venv
    @echo "Updating pre-commit hooks..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run pre-commit autoupdate

# Create virtual environment if it doesn't exist
venv:
    @if [ ! -d .venv ]; then \
        echo "Creating virtual environment..."; \
        uv venv .venv; \
        source .venv/bin/activate && uv pip sync pyproject.toml; \
    else \
        echo "Virtual environment already exists."; \
    fi

# Install/update Python dependencies
deps:
    @echo "Installing/updating dependencies..."
    @source .venv/bin/activate && uv pip sync pyproject.toml

# Clean up generated files and caches
clean:
    @echo "Cleaning up..."
    @find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    @find . -type f -name "*.pyc" -delete 2>/dev/null || true
    @find . -type f -name ".DS_Store" -delete 2>/dev/null || true
    @rm -rf .pytest_cache 2>/dev/null || true
    @rm -rf .mypy_cache 2>/dev/null || true
    @echo "✅ Cleanup complete!"

# Show test status for all components
status:
    @echo "==================================="
    @echo "ops-library Component Status"
    @echo "==================================="
    @echo ""
    @echo "Roles ($(ls -1 roles | wc -l) total):"
    @ls -1 roles | sed 's/^/  - /'
    @echo ""
    @echo "Run 'just test' to test everything"

# Show YAML lines of code statistics
stats:
    @cloc --include-lang=YAML --exclude-dir=.venv .

# Count total YAML lines
yaml-lines:
    @rg --files -0 -g '*.yml' -g '*.yaml' . | xargs -0 wc -l | awk 'BEGIN {sum=0} !/^ *[0-9]+ total$/ {sum += $1} END {print sum}'

# Show YAML lines of code per role (top 20)
stats-roles:
    #!/usr/bin/env bash
    printf "%-35s %6s\n" "ROLE" "LINES"
    printf "%-35s %6s\n" "-----------------------------------" "------"
    for dir in roles/*/; do
        role=$(basename "$dir")
        count=$(cloc --include-lang=YAML --csv --quiet "$dir" 2>/dev/null | tail -1 | cut -d',' -f5)
        printf "%-35s %6s\n" "$role" "${count:-0}"
    done | sort -t' ' -k2 -rn | head -20

# Quick test - just syntax and structure
quick: syntax-check
    @echo "Quick test completed!"

# Development workflow - test the role you're working on
dev ROLE:
    @echo "Testing {{ROLE}} for development..."
    @just test-role {{ROLE}}
    @just lint-role {{ROLE}} || true
    @echo "Development test complete for {{ROLE}}"

# Documentation commands
docs-build:
    @echo "Building documentation..."
    @uv run --extra docs sphinx-build -E -n -b html docs/source docs/build/html

docs-serve:
    @echo "Serving documentation at http://localhost:8000"
    @python3 -m http.server 8000 -d docs/build/html

docs-watch:
    @echo "Starting documentation watch mode..."
    @uv run --extra docs sphinx-autobuild docs/source docs/build/html --watch roles --watch README.md --watch ARCHITECTURE.md --watch TESTING.md --watch README_TESTING.md --watch CHANGELOG.md

docs-check:
    @echo "Checking documentation for broken links..."
    @uv run --extra docs sphinx-build -b linkcheck docs/source docs/build/linkcheck

docs-clean:
    @echo "Cleaning documentation build artifacts..."
    @uv run --extra docs sphinx-build -M clean docs/source docs/build

docs-lint:
    @echo "Validating documentation integrity..."
    @uv run python validate_docs.py

# ------------------------------------------
# Container runtime detection (Colima/Podman/Docker)
# ------------------------------------------

# Internal: Detect Docker host socket
# Priority: 1) Existing DOCKER_HOST env, 2) Colima socket, 3) Podman socket, 4) Default Docker socket
_detect-docker-host:
    #!/usr/bin/env bash
    if [[ -n "${DOCKER_HOST:-}" ]]; then
        echo "$DOCKER_HOST"
    elif [[ -S "$HOME/.colima/default/docker.sock" ]]; then
        echo "unix://$HOME/.colima/default/docker.sock"
    elif command -v podman &>/dev/null && podman machine inspect &>/dev/null 2>&1; then
        # Escape Go template braces to avoid just interpolation
        socket_path=$(podman machine inspect --format '{{"{{"}}.ConnectionInfo.PodmanSocket.Path{{"}}"}}' 2>/dev/null)
        if [[ -n "$socket_path" ]]; then
            echo "unix://$socket_path"
        else
            echo ""
        fi
    elif [[ -S /var/run/docker.sock ]]; then
        echo "unix:///var/run/docker.sock"
    else
        echo ""
    fi

# Helper: export DOCKER_HOST only if detection returns non-empty
_export-docker-host:
    #!/usr/bin/env bash
    detected=$(just _detect-docker-host)
    if [[ -n "$detected" ]]; then
        echo "export DOCKER_HOST='$detected'"
    else
        echo "# DOCKER_HOST: using system default"
    fi

# ------------------------------------------
# Molecule helpers
# ------------------------------------------

# Run molecule test for a specific role
molecule-test role:
    #!/usr/bin/env bash
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
    scripts/molecule-run.sh {{quote(role)}} default test

# Run a named molecule scenario for a specific role
molecule-test-scenario role scenario:
    #!/usr/bin/env bash
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
    scripts/molecule-run.sh {{quote(role)}} {{quote(scenario)}} test

# Run molecule converge (apply without destroy) for debugging
molecule-converge role:
    #!/usr/bin/env bash
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
    scripts/molecule-run.sh {{quote(role)}} default converge

# Run molecule verify (run verification tests only)
molecule-verify role:
    #!/usr/bin/env bash
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
    scripts/molecule-run.sh {{quote(role)}} default verify

# Destroy molecule test containers
molecule-destroy role:
    #!/usr/bin/env bash
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
    scripts/molecule-run.sh {{quote(role)}} default destroy

# SSH into running molecule container
molecule-login role:
    #!/usr/bin/env bash
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
    scripts/molecule-run.sh {{quote(role)}} default login

# Run molecule tests for all roles that have molecule configs
molecule-test-all:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1

    shopt -s nullglob
    molecule_files=(roles/*/molecule/*/molecule.yml)

    if [[ ${#molecule_files[@]} -eq 0 ]]; then
        echo "No roles with molecule tests found"
        exit 0
    fi

    failed_roles=()
    for molecule_file in "${molecule_files[@]}"; do
        role_name=$(basename "$(dirname "$(dirname "$(dirname "$molecule_file")")")")
        scenario_name=$(basename "$(dirname "$molecule_file")")
        echo "========================================"
        echo "Testing role: $role_name (scenario: $scenario_name)"
        echo "========================================"
        if ! scripts/molecule-run.sh "$role_name" "$scenario_name" test; then
            failed_roles+=("$role_name/$scenario_name")
        fi
    done

    if [[ ${#failed_roles[@]} -gt 0 ]]; then
        echo "========================================"
        echo "FAILED ROLES: ${failed_roles[*]}"
        echo "========================================"
        exit 1
    fi

    echo "All molecule tests passed!"

# Run molecule tests for all PostfixAdmin roles
molecule-test-postfixadmin:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1

    postfixadmin_roles=(
        "postfixadmin_deploy"
        "postfixadmin_backup"
        "postfixadmin_restore"
        "postfixadmin_remove"
    )

    failed_roles=()
    for role in "${postfixadmin_roles[@]}"; do
        if [[ -d "roles/$role/molecule" ]]; then
            echo "========================================"
            echo "Testing role: $role"
            echo "========================================"
            if ! scripts/molecule-run.sh "$role" default test; then
                failed_roles+=("$role")
            fi
        else
            echo "Skipping $role (no molecule tests)"
        fi
    done

    if [[ ${#failed_roles[@]} -gt 0 ]]; then
        echo "========================================"
        echo "FAILED ROLES: ${failed_roles[*]}"
        echo "========================================"
        exit 1
    fi

    echo "All PostfixAdmin molecule tests passed!"

# Help
help:
    @echo "ops-library Testing Commands"
    @echo ""
    @echo "Quick commands:"
    @echo "  just test           # Role tests + lint summary + strict docs checks"
    @echo "  just validate-strict # Role tests + failing lint + strict docs checks"
    @echo "  just test-roles     # Test all roles"
    @echo "  just lint-strict    # Fail on ansible-lint issues"
    @echo "  just lint           # Summary-only ansible-lint helper"
    @echo "  just syntax-check   # Quick syntax validation"
    @echo ""
    @echo "Specific testing:"
    @echo "  just test-role fastdeploy_register_service"
    @echo "  just lint-role test_dummy"
    @echo ""
    @echo "Molecule (Docker-based integration tests):"
    @echo "  just molecule-test <role>         # Full test cycle for a role"
    @echo "  just molecule-converge <role>     # Apply without destroy (debugging)"
    @echo "  just molecule-verify <role>       # Run verification tests only"
    @echo "  just molecule-destroy <role>      # Destroy test containers"
    @echo "  just molecule-login <role>        # SSH into running container"
    @echo "  just molecule-test-all            # Test all roles with molecule"
    @echo "  just molecule-test-postfixadmin   # Test all PostfixAdmin roles"
    @echo ""
    @echo "Documentation:"
    @echo "  just docs-build     # Build documentation"
    @echo "  just docs-serve     # Serve documentation locally"
    @echo "  just docs-watch     # Watch and rebuild documentation"
    @echo "  just docs-check     # Check for broken links"
    @echo "  just docs-clean     # Clean build artifacts"
    @echo "  just docs-lint      # Validate documentation"
    @echo ""
    @echo "Setup:"
    @echo "  just setup          # Setup dev environment"
    @echo "  just venv           # Create virtual environment"
    @echo "  just deps           # Install dependencies"
    @echo ""
    @echo "Info:"
    @echo "  just status         # Show component overview"
    @echo "  just stats          # Show YAML lines of code (requires cloc)"
    @echo "  just yaml-lines     # Show total YAML line count"
    @echo "  just stats-roles    # Show YAML lines per role (top 20)"
    @echo ""
    @echo "Run 'just' to see all available commands"

test-opaq-app-deploy: venv
    @echo "Testing the Opaq app deployment contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_opaq_app_deploy

test-static-site-deploy: venv
    @echo "Testing static-site deployment security and publication contracts..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_static_site_deploy

# Test Voxhelm CSRF origin configuration
test-voxhelm-parakeet: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_voxhelm_parakeet

test-voxhelm-csrf: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_voxhelm_csrf

# Voxhelm prune launchd job plus optional Voxhelm/Echoport/mailgun-relay settings.
test-voxhelm-prune-and-service-knobs: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_voxhelm_prune_and_service_knobs

# Collection-wide policy: role templates omit the HSTS preload directive.
test-traefik-hsts: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_traefik_hsts

test-traefik-frame-options: venv
    @echo "Testing that no Traefik edge weakens a backend's X-Frame-Options..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_traefik_frame_options

# Traefik postrotate must make the running Traefik reopen its logs (SIGUSR1).
test-traefik-logrotate: venv
    @echo "Testing that Traefik log rotation reopens the log files..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_traefik_logrotate

# Static check: files rendered with secrets are not world-readable.
test-secret-file-modes: venv
    @echo "Testing that secret-bearing templates set restrictive modes..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_secret_file_modes

# Static check: piped shell tasks set pipefail; mail backup/restore dump checks.
test-shell-pipefail: venv
    @echo "Testing that piped shell tasks cannot hide a failed command..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_shell_pipefail

test-graphyard-auth-bootstrap-changed-when: venv
    @echo "Testing the Graphyard auth bootstrap status-line checks (provisioning rewrite, Grafana password)..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_graphyard_auth_bootstrap_changed_when tests.test_graphyard_auth_bootstrap_password_check

test-homeassistant-uv-system-certs: venv
    @echo "Testing the Home Assistant UV_SYSTEM_CERTS drop-in checks and wiring..."
    @ANSIBLE_COLLECTIONS_PATH="$(scripts/checkout-collections-path.sh)" UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_homeassistant_uv_system_certs

test-python-security-floor: venv
    @echo "Testing certifi/pip security floors (filters, resolver lifecycle, collection loader, role wiring)..."
    @ANSIBLE_COLLECTIONS_PATH="$(scripts/checkout-collections-path.sh)" UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_python_security_floor tests.test_python_security_floor_roles

test-metube-uv-sync-changed-when: venv
    @echo "Testing that MeTube's uv sync reports changed only on package changes..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_metube_uv_sync_changed_when

test-ansible-core-floor: venv
    @echo "Testing that the collection and its test environment require ansible-core >= 2.20.3..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_ansible_core_floor

test-backup-service-restart: venv
    @echo "Testing that backup roles restart stopped services in an always block..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_backup_service_restart

# Live software observation contracts; no network or host mutations.
test-software-live: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -W error::ResourceWarning -m unittest tests.test_software_live tests.test_software_health_bridge

# rust/software-live/PLAN.md 7.3/8.1: the role's switch between Python and the
# Rust release (filters, templates, ansible-playbook runs against localhost
# with fakes; macOS needs Homebrew coreutils for GNU mv)
test-software-live-impl: venv
    @echo "Testing the software_live switch between Python and Rust (drop-ins, shadow, pins, prune)..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_software_live_impl

# rust/software-live/PLAN.md 6.1: fixtures regenerate byte-identical, TESTMAP names every Python test.
# software-live Rust port: its fixtures and TESTMAP still match the Python program
test-software-live-rust-fixtures: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -W error::ResourceWarning -m unittest tests.test_software_live_rust_fixtures

# Generates under Python 3.12 (Ubuntu hosts), requires the same output under 3.13 (Debian).
# software-live Rust port: regenerate its fixtures from the Python program
rs-software-live-fixtures:
    @uv run --python 3.12 --no-project python -I rust/software-live/fixtures/generate.py
    @uv run --python 3.13 --no-project python -I rust/software-live/fixtures/generate.py --check

# rust/software-live/PLAN.md 6.4. Run it from a worktree; it writes rust/target/.
# software-live Rust port: cargo fmt --check, clippy -D warnings and tests of its crate
rs-software-live:
    #!/usr/bin/env bash
    set -euo pipefail
    cd rust
    cargo fmt -p software-live --check
    cargo clippy -p software-live --all-targets --locked -- -D warnings
    cargo test -p software-live --locked

# rust/software-live/PLAN.md 7.4, 13.6: the `software-live-apt` CI job in Docker (variants: ubuntu24.04 debian13; default both).
# software-live Rust port: the APT helper's checks and python-apt comparison in its variant containers
rs-software-live-apt *variants:
    @rust/software-live-apt/container/docker-check.sh {{variants}}

# Typed Python added by the software observation roles.
typecheck: venv
    @uv run --with mypy mypy --ignore-missing-imports --check-untyped-defs roles/software_estate/files/collect.py roles/software_estate/files/emit.py roles/software_estate/files/outbox.py roles/software_estate/files/send.py roles/software_estate/files/publish.py roles/software_estate/files/vector_inventory_config.py roles/software_estate/files/sbom.py roles/software_live/files/software_live.py roles/software_live/files/nyxmon_checks.py roles/traefik_deploy/files/traefik_transaction.py roles/traefik_deploy/files/traefik_control.py roles/zfs_usb_replication/files/zfs_usb_bookmark_anchors.py roles/zfs_usb_replication/files/zfs_usb_replication_state.py roles/zfs_usb_replication/files/zfs_usb_snapshot_retention.py roles/ca_trust_consumers/files/ca_trust_roots_check.py plugins/filter/ca_trust_consumers.py roles/ca_trust_consumers/files/ca_trust_sudoers_env_file.py plugins/filter/rust_release.py plugins/filter/echoport_guard.py plugins/filter/metrics_httpd.py plugins/filter/software_live_impl.py roles/rustup_security/files/rustup_security.py

# Exercise guarded binary/config transactions and controller failure journaling.
test-unifi-traefik-allowlist: venv
    @echo "Testing the optional UniFi Traefik IP allowlist (default unchanged, validation)..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_unifi_traefik_allowlist
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_unifi_traefik_allowlist.yml

test-paperless-backup-exposure: venv
    @echo "Testing that the Paperless backup archive is owner-only and the listener address is a setting..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_paperless_backup_exposure

# Static and localhost check: fetched backup archives are owner-only on the controller.
test-traefik-backup-dynamic: venv
    @echo "Testing that traefik_backup archives the dynamic route configs..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_traefik_backup_dynamic

test-fetched-backup-archive-modes: venv
    @echo "Testing that fetched backup archives are 0600 on the controller..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_fetched_backup_archive_modes

test-minio-metadata-backup: venv
    @echo "Testing metadata-only MinIO backup and restore gating..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_minio_metadata_backup

# MINIO_TEST_IMAGE (default in the Dockerfile) must be available locally or
# pullable for the Docker host's architecture.
test-minio-backup-molecule: venv
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just _export-docker-host)"
    docker build -q -t ops-library-molecule-minio-backup:local \
        ${MINIO_TEST_IMAGE:+--build-arg MINIO_TEST_IMAGE="$MINIO_TEST_IMAGE"} \
        roles/minio_backup/molecule/default
    just molecule-test minio_backup

test-backup-archive-modes: venv
    @echo "Testing that backup archives on the host are 0600 and older ones get tightened..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_backup_archive_modes

test-traefik-backup-molecule: venv
    @just molecule-test traefik_backup

test-logyard-ingress: venv
    @echo "Testing that the Logyard ingress routes only the Loki push path and /ready..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_logyard_ingress

# Static check: Molecule platform/network names carry ${MOLECULE_RUN_ID:-local}
# so parallel runs from different checkouts never share Docker containers.
test-molecule-run-isolation: venv
    @echo "Testing that Molecule container names are scoped to the run..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_molecule_run_isolation

test-delve-recorder-flags: venv
    @echo "Testing the optional Delve legacy/notification flags and the recorder chunk cap..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-playbook -i localhost, -c local tests/test_delve_recorder_flags.yml

test-server-ad-analysis: venv
    @echo "Testing Delve's server ad analysis settings, the llama-server role and the worker profile runtime..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_server_ad_analysis

test-traefik-transactions: venv
    @uv run python -m unittest tests.test_traefik_transaction

# Disposable real systemd/Traefik ARM64 fixture; requires the two verified archives.
test-traefik-transactions-integration ARTIFACTS: venv
    @uv run python scripts/run-traefik-transaction-integration.py {{quote(ARTIFACTS)}}

# Local lifecycle and HTTPS tests; no live infrastructure mutations.
test-macos-ssh-tunnel: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_macos_ssh_tunnel

test-macos-smb-mount-keeper: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_macos_smb_mount_keeper

# Managed OpenClaw heartbeat recovery hooks
test-openclaw-heartbeat-recovery: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run pytest -q tests/unit/test_openclaw_heartbeat_recovery.py

test-daybook-operations: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_daybook_operations tests.test_daybook_operations_backup_bridge tests.test_daybook_operations_service_token tests.test_daybook_launchd_closeout tests.test_daybook_operations_runtime_stop

# Read-only application/host software discovery.
test-software-estate: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_software_estate tests.test_inventory_emit tests.test_inventory_send tests.test_inventory_publish tests.test_inventory_publisher_linux

# Verify full reindexing and service pause/recovery.
test-paperless-search-index: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_paperless_search_index

test-docker-cache-cleanup: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_docker_cache_cleanup

# Verify the read-only time synchronization check (parsers, thresholds, messages).
test-time-sync-check: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_time_sync_check

# Verify literal subject matching for the scoped delivery-probe exemption,
# and run the relay probe script and the metrics endpoint's probe-state export
# against local stubs.
test-mail-monitoring-probe: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run pytest -q tests/unit/test_mail_monitoring_probe_settings.py tests/unit/test_mailgun_relay_probe.py

# Portable render/static audit regressions; no Molecule or host access.
test-lowfindings: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run pytest -q tests/test_lowfindings.py

# Audit L4 release-download regression gate
test-root-downloads: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python scripts/check_root_downloads.py
    @UV_PROJECT_ENVIRONMENT=.venv uv run pytest -q tests/test_root_downloads.py

# Portable task credential delivery regressions (no host/database access).
# Static check: tasks that become an unprivileged user must not put secrets into
# the task environment (sudo logs it) or onto the command line.
test-become-environment-secrets: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_become_environment_secrets

test-task-credentials: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest discover -s tests -p 'test_*_credentials.py'
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_task_credential_contracts

test-aws-ca-bundle: venv
    @uv run python -m unittest tests.test_aws_ca_bundle

# Exercise the real Java keytool transformation and recovery guards.
test-macos-java-trust: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_macos_java_trust -v

# Dependency preflight for incident trust remediation.
test-security-trust-remediate: venv
    @uv run python -m unittest tests.test_security_trust_remediate

test-macos-ca-remediate:
    @python3 -m unittest tests.test_macos_ca_remediate


test-linuxserver-ca-remediate: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_linuxserver_ca_remediate


test-macos-python-ca-remediate: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_macos_python_ca_remediate


test-container-ca-remediate:
    @python3 -m unittest tests.test_container_ca_remediate


test-chrome-ca-distrust: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_chrome_ca_distrust

# Validate trust-only activation and recovery
test-container-ca-activate: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_container_ca_activate tests.test_livekit_idle_preflight tests.test_container_ca_owners

# Verify idle and launchd trust refresh guards
test-voxhelm-trust-refresh: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_voxhelm_trust_refresh

# NODE_OPTIONS merging, forbidden-root scan and restart gating for ca_trust_consumers.
test-ca-trust-consumers: venv
    @UV_PROJECT_ENVIRONMENT=.venv uv run python -m unittest tests.test_ca_trust_consumers tests.test_ca_trust_consumers_run

# Explicit required Docker/real-UV recovery integration gate.
test-security-trust-recover: venv
    @uv run python -m unittest tests.test_security_trust_recover_live

# Guarded manager-only Rustup security patch contracts.
test-rustup-security: venv
    @uv run python -m unittest tests.test_rustup_security

# Opt-in real pinned updater fixture; local disposable homes/containers only.
test-rustup-security-native:
    @python3 tests/run_rustup_security_native.py

# Opt-in privileged isolated real-systemd/nested-Docker regression (local Docker only).
test-container-ca-owner-systemd:
    @python3 tests/run_container_ca_owner_systemd.py
