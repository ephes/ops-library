# Changelog

All notable changes to the ops-library collection will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Breaking Changes
- **Python 3.11+ required** - Dropped support for Python 3.8, 3.9, and 3.10
  - Supports Python 3.11, 3.12, 3.13 (following N-2 version support policy)
  - All roles and testing infrastructure now require Python 3.11+
  - Update your systems before upgrading to this version
- **ansible-core 2.15+ required** - Dropped support for Ansible 2.9-2.14
  - ansible-core 2.15 is the minimum version compatible with Python 3.11+
  - Update your Ansible installation before upgrading

### Added
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
- Paperless-ngx suite: `paperless_deploy`, `paperless_backup`, `paperless_restore`, `paperless_postgres`, and `paperless_remove` roles for deployment, disaster recovery, and safe removal
- `redis_install` role to provision standalone Redis instances with optional authentication, persistence, and memory tuning
- `postgres_install` role to install PostgreSQL with manageable config, databases, users, and extensions
- `minio_deploy` role to provision MinIO with dual-router Traefik exposure, security hardening, and optional client bootstrapping
- `minio_remove` role to destructively remove MinIO with confirmation, optional data preservation, and Traefik cleanup
- Dynamic DNS support in `dns_deploy`, adding an opt-in LiveDNS updater with dedicated service accounts, timers, and IPv4/IPv6 support

### Changed
- Updated README.md with prominent link to ReadTheDocs
- Updated repository URLs to https://github.com/ephes/ops-library
- Modernized Python tooling: uv replaces traditional pip/venv workflow
- Removed `docs-setup` command (auto-handled by uv)
- `fastdeploy_deploy` now depends on `postgres_install` for database provisioning (removing the legacy inline PostgreSQL tasks)
- `uv_install` detects alternate uv installations, relinks to newer binaries automatically, and enables `uv_update_existing` by default to keep hosts current
- `fastdeploy_deploy` implements Traefik's dual-router pattern with IP-based allow lists, bcrypt-hashed basic auth, security headers, and compression middleware
- Paperless roles now support Python 3.14 and include an optional ocrmypdf patch to keep OCR workflows unblocked
- `redis_install` enables config validation by default to catch syntax and runtime issues before service restarts
- `nyxmon_deploy` and `homelab_deploy` switch from Granian to Gunicorn and gained configurable Python version management (defaulting to 3.13)
- `nyxmon_deploy` now enforces the same dual-router authentication policy as other public services, including validation and hashed credentials
- DNS deployment/removal flows hardened with improved resolver management, legacy `unbound_only` port detection, and safer variable validation

### Fixed
- Home Assistant presence automations now include the default file to prevent missing automation imports after deployment
- `dns_remove` cleans up DDNS units reliably and no longer crashes on undefined variables during selective removal

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
