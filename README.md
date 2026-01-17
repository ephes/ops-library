# Ops Library

A collection of reusable Ansible roles for homelab automation and service deployment.

📖 **[Full Documentation](https://ops-library.readthedocs.io/)** | 📚 [Architecture](./ARCHITECTURE.md) | 🧪 [Testing](./TESTING.md)

## Quick Start

```bash
# Build and install the collection locally
ansible-galaxy collection build .
ansible-galaxy collection install local-ops_library-*.tar.gz -p ../ops-control/collections

# Or use from ops-control
cd ../ops-control
just install-local-library
```

## Python Runtimes

Service roles that need specific Python versions rely on `uv` to install and manage interpreters
(for example `wagtail_deploy`, `homeassistant_deploy`, `fastdeploy_deploy`). Prefer `uv` instead of
system Python builds; set `uv_version` and the role-specific `*_python_version` variables as needed.

## Available Roles

The table below links each published role to its dedicated documentation. Refer to the role README for full variable reference, workflows, and examples.

| Category | Role | Summary |
|----------|------|---------|
| Storage | [`zfs_pool_deploy`](roles/zfs_pool_deploy/README.md) | Create/manage encrypted ZFS pools with safety toggles and boot-time unlock wiring. |
| Storage | [`zfs_dataset`](roles/zfs_dataset/README.md) | Create/manage ZFS datasets with property support and optional macOS SMB compatibility defaults. |
| Storage | [`sanoid`](roles/sanoid/README.md) | Configure sanoid snapshot policies and a dedicated systemd timer. |
| Storage | [`hdparm_tune`](roles/hdparm_tune/README.md) | Configure persistent hdparm power settings (APM/spindown) for disks. |
| Infrastructure | [`netplan_config`](roles/netplan_config/README.md) | Configure persistent netplan networking. |
| Monitoring | [`smartd`](roles/smartd/README.md) | Configure smartmontools smartd for HDD/NVMe monitoring and scheduled tests. |
| Monitoring | [`zed`](roles/zed/README.md) | Configure ZFS Event Daemon notifications and optional zpool scrub timers. |
| Monitoring | [`nyxmon_storage_exporter`](roles/nyxmon_storage_exporter/README.md) | Install `nyxmon-storage-metrics` JSON exporter for storage health monitoring via HTTP endpoints. |
| Infrastructure | [`mail_relay_client`](roles/mail_relay_client/README.md) | Configure a minimal Postfix setup for relaying outbound alert mail via a smarthost. |
| File sharing | [`samba_timemachine`](roles/samba_timemachine/README.md) | Configure Samba Time Machine share with vfs_fruit and conf.d snippet wiring. |
| File sharing | [`samba_share`](roles/samba_share/README.md) | Configure generic Samba shares via conf.d snippets and user provisioning. |
| Infrastructure | [`encrypted_volume_prepare`](roles/encrypted_volume_prepare/README.md) | Prepare and mount a LUKS data volume with UUID checks, keyfile unlock, and boot-time wiring (crypttab/fstab). |
| Infrastructure | [`traefik_deploy`](roles/traefik_deploy/README.md) | Deploy Traefik reverse proxy with Let's Encrypt (auto-detects platform, version upgrades). |
| Infrastructure | [`tailscale_deploy`](roles/tailscale_deploy/README.md) | Install Tailscale from the official repo and join tailnet with auth key or manual mode (accept-dns defaults to false). |
| Infrastructure | [`bind_authoritative_deploy`](roles/bind_authoritative_deploy/README.md) | Deploy authoritative BIND 9 with managed configs and zone files. |
| Service deployment | [`fastdeploy_deploy`](roles/fastdeploy_deploy/README.md) | Deploy the FastDeploy platform (database, uv, frontend build, systemd, Traefik). |
| Service deployment | [`nyxmon_deploy`](roles/nyxmon_deploy/README.md) | Deploy Nyxmon (Django app, monitoring agent, Telegram integration). |
| Service deployment | [`homeassistant_deploy`](roles/homeassistant_deploy/README.md) | Deploy Home Assistant Core with uv-managed Python env, Traefik, and systemd. |
| Service deployment | [`unifi_deploy`](roles/unifi_deploy/README.md) | Install UniFi Network Application with MongoDB 8.0, Java 17, Traefik + UFW wiring, and optional HA integration. |
| Service deployment | [`navidrome_deploy`](roles/navidrome_deploy/README.md) | Deploy Navidrome music server (binary/systemd, Traefik, optional rescan timer). |
| Service deployment | [`jellyfin_deploy`](roles/jellyfin_deploy/README.md) | Deploy Jellyfin media server (apt packages, systemd, Traefik with basic auth). |
| Service deployment | [`metube_deploy`](roles/metube_deploy/README.md) | Deploy MeTube (yt-dlp web UI) from source with uv, Angular build, systemd, and Traefik internal-bypass/basic-auth. |
| Service deployment | [`open_webui_deploy`](roles/open_webui_deploy/README.md) | Deploy Open WebUI (Docker Compose) with Traefik routing and optional basic auth. |
| Service deployment | [`mail_backend_deploy`](roles/mail_backend_deploy/README.md) | Deploy mail backend with Postfix, Dovecot, OpenDKIM, and PostgreSQL virtual users/domains. |
| Service deployment | [`mail_relay_deploy`](roles/mail_relay_deploy/README.md) | Deploy Postfix edge relay with greylisting, TLS termination, and backend routing. |
| Service deployment | [`snappymail_deploy`](roles/snappymail_deploy/README.md) | Deploy SnappyMail webmail via PHP-FPM + nginx with Traefik exposure and IMAP/SMTP defaults. |
| Service deployment | [`takahe_deploy`](roles/takahe_deploy/README.md) | Deploy Takahe with systemd, nginx cache/accel proxying, and Traefik exposure. |
| Service deployment | [`wagtail_deploy`](roles/wagtail_deploy/README.md) | Deploy Wagtail Django sites with uv, systemd, and Traefik routing. |
| Service deployment | [`mastodon_deploy`](roles/mastodon_deploy/README.md) | Deploy Mastodon from source with rbenv+nvm, systemd services, and Traefik routing. |
| Monitoring | [`metrics_endpoint`](roles/metrics_endpoint/README.md) | Expose an authenticated JSON health endpoint (e.g. `/.well-known/health`) for nyxmon checks. |
| Monitoring | [`mail_monitoring`](roles/mail_monitoring/README.md) | Provision monitor mailbox + cleanup timer to support nyxmon end-to-end mail flow checks. |
| Service operations | [`tailscale_backup`](roles/tailscale_backup/README.md) | Backup `/var/lib/tailscale`, sysconfig, and systemd drop-ins to preserve node identity. |
| Service operations | [`tailscale_restore`](roles/tailscale_restore/README.md) | Restore Tailscale state from archive and optionally rerun `tailscale up`. |
| Service operations | [`homeassistant_backup`](roles/homeassistant_backup/README.md) | Take on-host + off-host backups (rsync + manifest + optional archives). |
| Service operations | [`homeassistant_restore`](roles/homeassistant_restore/README.md) | Restore Home Assistant from validated snippets with rollback safety. |
| Service operations | [`unifi_backup`](roles/unifi_backup/README.md) | Snapshot UniFi (mongodump + rsync + manifests + optional archive fetch). |
| Service operations | [`unifi_restore`](roles/unifi_restore/README.md) | Restore UniFi with safety backups, version checks, rollback, and health verification. |
| Service operations | [`navidrome_backup`](roles/navidrome_backup/README.md) | Backup Navidrome data/config/systemd/Traefik with optional archive fetch. |
| Service operations | [`navidrome_restore`](roles/navidrome_restore/README.md) | Restore Navidrome archives and optionally trigger a full rescan. |
| Service operations | [`takahe_backup`](roles/takahe_backup/README.md) | Backup Takahe database, media, and configuration with manifests and archive fetch. |
| Service operations | [`takahe_restore`](roles/takahe_restore/README.md) | Restore Takahe from archives, replaying the database and media content. |
| Service operations | [`wagtail_backup`](roles/wagtail_backup/README.md) | Backup Wagtail PostgreSQL databases with manifest + optional archive fetch. |
| Service operations | [`wagtail_restore`](roles/wagtail_restore/README.md) | Restore Wagtail databases from archives and restart the service. |
| Service operations | [`jellyfin_backup`](roles/jellyfin_backup/README.md) | Backup Jellyfin data/config/systemd/Traefik with optional archive fetch. |
| Service operations | [`jellyfin_restore`](roles/jellyfin_restore/README.md) | Restore Jellyfin archives back into place and restart the service. |
| Service operations | [`metube_backup`](roles/metube_backup/README.md) | Backup MeTube state/env/systemd/Traefik with optional archive fetch. |
| Service operations | [`metube_restore`](roles/metube_restore/README.md) | Restore MeTube from archives produced by `metube_backup`. |
| Service operations | [`mastodon_backup`](roles/mastodon_backup/README.md) | Backup Mastodon database, media, and configuration with optional archive fetch. |
| Service operations | [`mastodon_restore`](roles/mastodon_restore/README.md) | Restore Mastodon from archives produced by `mastodon_backup`. |
| Service operations | [`mastodon_maintenance`](roles/mastodon_maintenance/README.md) | Run Mastodon tootctl maintenance commands (media cleanup, cache pruning). |
| Service removal | [`fastdeploy_remove`](roles/fastdeploy_remove/README.md) | Remove FastDeploy and related resources safely. |
| Service removal | [`nyxmon_remove`](roles/nyxmon_remove/README.md) | Remove Nyxmon while preserving data as needed. |
| Service removal | [`homeassistant_remove`](roles/homeassistant_remove/README.md) | Tear down Home Assistant (service, config, user) with confirmation guards. |
| Service removal | [`unifi_remove`](roles/unifi_remove/README.md) | Destructively remove UniFi, MongoDB packages/users, Traefik + firewall artifacts with confirmation. |
| Service removal | [`navidrome_remove`](roles/navidrome_remove/README.md) | Remove Navidrome binaries, config, data, Traefik wiring, and user with confirmation toggles. |
| Service removal | [`takahe_remove`](roles/takahe_remove/README.md) | Remove Takahe services, configs, and user with confirmation guards. |
| Service removal | [`tailscale_remove`](roles/tailscale_remove/README.md) | Remove Tailscale packages/repo, optionally logout and purge `/var/lib/tailscale`. |
| Service removal | [`jellyfin_remove`](roles/jellyfin_remove/README.md) | Remove Jellyfin packages, config/data/logs, Traefik wiring, and user with confirmation toggles. |
| Service removal | [`metube_remove`](roles/metube_remove/README.md) | Remove MeTube service, env/state/Traefik wiring, optional downloads, with confirmation guard. |
| Service removal | [`open_webui_remove`](roles/open_webui_remove/README.md) | Remove Open WebUI service, compose files, Traefik wiring, and optional data. |
| Service removal | [`mastodon_remove`](roles/mastodon_remove/README.md) | Remove Mastodon services, config, and user with confirmation gates. |
| Service removal | [`ollama_remove`](roles/ollama_remove/README.md) | Remove Ollama launchd service on macOS with optional data/user/brew cleanup. |
| Service registration | [`apt_upgrade_register`](roles/apt_upgrade_register/README.md) | Register apt-upgrade maintenance runners with FastDeploy. |
| Service registration | [`fastdeploy_register_service`](roles/fastdeploy_register_service/README.md) | Generic FastDeploy service registration helper. |
| Bootstrap | [`ansible_install`](roles/ansible_install/README.md) | Ensure controller has Ansible and required plugins. |
| Bootstrap | [`shell_basics_deploy`](roles/shell_basics_deploy/README.md) | Install fish, modern CLI tools (btop, bmon, sysstat/iotop, tealdeer, eza), set shell/editor defaults, and keep chezmoi current from upstream. |
| Bootstrap | [`docker_install`](roles/docker_install/README.md) | Install Docker Engine + Docker Compose v2 (plugin) from the official Docker apt repository. |
| Bootstrap | [`dpkg_arch_remove`](roles/dpkg_arch_remove/README.md) | Remove foreign dpkg architectures (defaults to i386) and optionally purge packages. |
| Bootstrap | [`ollama_install`](roles/ollama_install/README.md) | Install Ollama on macOS via Homebrew and manage a launchd service. |
| Bootstrap | [`uv_install`](roles/uv_install/README.md) | Install uv for Python environment management. |
| Bootstrap | [`sops_dependencies`](roles/sops_dependencies/README.md) | Install age/SOPS prerequisites. |
| Testing/demo | [`test_dummy`](roles/test_dummy/README.md) | Demonstration service for developing and testing runners. |

## Development

### Testing
```bash
# Run all tests
just test

# Test specific role
just test-role fastdeploy_deploy
just test-role traefik_deploy

# Or run test playbooks directly
ansible-playbook tests/test_traefik_deploy.yml -i tests/inventory/test.yml
```

### Pre-commit Hooks
```bash
# Install pre-commit hooks
just install-hooks
```

### Statistics
```bash
# Show YAML lines of code (requires cloc)
just stats

# Show YAML lines per role (top 20)
just stats-roles
```

## Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) - System design and patterns
- [CHANGELOG.md](./CHANGELOG.md) - Version history and changes
- [TESTING.md](./TESTING.md) - Testing guidelines
- [Role-specific READMEs](./roles/) - Detailed documentation per role
- [README_TEMPLATE.md](./roles/README_TEMPLATE.md) - Template for role documentation

## Requirements

- **ansible-core 2.20+** (Ansible 2.9 no longer supported)
- **Python 3.14+** (3.8-3.13 no longer supported as of v3.0.0)
- Collections: `community.general`, `ansible.posix`

> **Note:** This collection follows an N-2 Python version support policy, supporting the current release and two prior minor versions (currently 3.14).

## License

MIT
