# Service Lifecycle Guide

This guide explains how to add a brand-new service to the ops-library/ops-control pairing without missing any of the moving parts (roles, documentation, tests, and metadata). Use it whenever you introduce a service such as `homeassistant`, `minio`, or any future workload that needs deploy/backup/restore/remove coverage, or an approved backup/restore exception.

```{admonition} Document meta
:class: tip
**Last updated:** 2026-02-23  
**Version:** 1.2 (bump this when the checklist materially changes)  
**Feedback:** open a GitHub issue in `ops-library` or mention it in the ops-control stand-up notes so we can track improvements.
```

## Where This Documentation Lives

- **ops-library** hosts the reusable, public automation and therefore the canonical documentation for how service roles are structured. Keep this guide here so contributors see it next to the role source and Sphinx docs (`just docs-build` → `just docs-serve`).
- **ops-control** consumes the collection. After you publish a service in ops-library you wire it into ops-control via metadata/secrets, but the “how to build roles” contract belongs in ops-library.

## Lifecycle Checklist

Follow this sequence for every service.

```{admonition} Example: Adding the "miniflux" service
1. **Slug:** `miniflux`
2. **Roles:** `miniflux_deploy`, `miniflux_backup`, `miniflux_restore`, `miniflux_remove`, and an optional `miniflux_shared` helper.
3. **services-metadata.yml entry:**

   ```yaml
   miniflux:
     description: "RSS reader"
     default_host: macmini
     capabilities: [deploy, backup, restore, remove]
     required_secrets:
       - miniflux_admin_password
       - miniflux_db_password
   ```

4. **Service directories:**

   ```
   roles/
     miniflux_deploy/
     miniflux_backup/
     miniflux_restore/
     miniflux_remove/
     miniflux_shared/
   ```

5. **Shared role inclusion:**

   ```yaml
   - name: Load shared facts and paths
     ansible.builtin.include_role:
       name: local.ops_library.miniflux_shared
   ```
```

### 1. Define the service slug and metadata

1. Pick a short slug (e.g. `paperless`, `unifi`). This slug becomes the prefix for all ops-library roles (`paperless_deploy`, `paperless_backup`, etc.) and the key in `ops-control/services-metadata.yml`.
2. Update `ops-control/services-metadata.yml`:
   - Describe the service, default host, and capabilities. Capabilities map 1:1 to the default suffixes (`deploy`, `backup`, `restore`, `remove`) and drive the `just` helpers. Add `register` or other custom capabilities only when you provide a role for that action.
   - List `required_secrets` (even if empty) so `just create-secrets` knows which values to prompt for.
   - Specify overrides if a lifecycle uses a non-standard role name (see the `redis` example which uses `redis_install` instead of `<slug>_deploy`).
3. Create an encrypted secrets file in `ops-control/secrets/<env>/<service>.yml` so automation has a home for credentials from day one.
4. Confirm defaults such as `backup_root_prefix` in `services-metadata.yml` align with your service needs (`/opt/backups/<service>/` on remote hosts and `~/backups/<service>/` locally are the common pattern).

#### Lifecycle exception: centralized backup/restore orchestration

Some services are intentionally backed up and restored via a centralized orchestrator such as Echoport instead of `<service>_backup` / `<service>_restore` roles.

If you use this exception:

1. Document the exception in the service spec/PRD and the operator runbook (include the exact command path operators must use).
2. Do not advertise unsupported capabilities in `services-metadata.yml`. If there is no `<service>_backup` or `<service>_restore` role, do not list `backup`/`restore` capabilities.
3. Provide equivalent restore-drill evidence and operator commands in the runbook (for example: manual backup trigger, restore command, and post-restore health checks).

### 2. Create service roles inside ops-library

For each advertised capability add a role under `roles/<service>_<action>/`. Re-use shared snippets (templated configs, facts, path calculations) by putting them in `roles/<service>_shared/` and including that role where needed. Offer both rsync (local dev) and git (production) deployment modes whenever the codebase lives in git. If you use a centralized backup/restore exception, omit backup/restore roles and document the alternate flow.

- **rsync mode** is ideal for hacking on a role locally (`just deploy-one <service> dev`). It pushes whatever is under `{{ service_repo_path }}`.
- **git mode** is for production/staging where FastDeploy or CI clones a clean tag/branch and reduces drift.

#### Deploy role

- Validates every required variable and secret up front with `assert`.
- Owns OS packages, users/groups, cache directories, and systemd units.
- Provides Traefik/UFW wiring, health checks, and idempotent upgrades (rsync and git modes where the service code lives in source control).

#### Backup role

- Dumps all state (databases, media, config) to `{{ backup_root_prefix }}/<service>/`. `backup_root_prefix` defaults to `/opt/backups` via metadata but can be overridden per host.
- Writes manifest files so restore can verify archives.
- Supports optional local fetch (rsync/scp) triggered by ops-control `just backup <service>`.

#### Restore role

- Validates archives/manifests and performs safety snapshots before destructive actions.
- Restores files/databases and brings services back online.
- Exposes `restore-check` mode for dry runs when feasible.

#### Remove role

- Deletes services safely with confirmation toggles (`service_confirm_removal`, `service_remove_data`, etc.).
- Removes users, configs, systemd units, and reverse-proxy artifacts as requested.

#### Optional roles

- `*_register` roles wire FastDeploy runners for ongoing maintenance.
- `*_shared` roles encapsulate tasks (e.g., path calculations, templates) that other lifecycle roles import via `include_role`.

#### Role dependencies and shared infrastructure

- If a service depends on shared infrastructure (PostgreSQL, Redis, Traefik, firewall rules), document the expectation in the deploy role README and add asserts that verify the dependency (e.g., `postgres_host` reachable, Traefik dynamic config path exists).
- For hard dependencies, include or require the bootstrap roles (`postgres_install`, `redis_install`, etc.) and clearly separate which steps run on the controller vs. the target host.

### 3. Document each role

1. Each role requires a README based on `roles/README_TEMPLATE.md`. Include usage examples, variable tables, and recovery instructions.
2. Add Sphinx reference pages under `docs/source/roles/<category>/<role>.md` (copy from an existing role). Categories map to directories already present: `deployment`, `operations`, `removal`, `registration`, `bootstrap`, and `testing`. Update the relevant `index.md` file to include the new document so `just docs-build` picks it up. Missing toctree entries are why services disappear from local docs.
3. Reference this guide wherever it helps (e.g., mention “see the Service Lifecycle Guide for the full checklist” inside role docs).

### 4. Testing requirements

- Integration tests live under `tests/` (playbooks such as `tests/test_<role>.yml`) and rely on `test_roles.py`. Longer-running suites or utilities can sit under `ops_library_testing/` if they need Python helpers.
- Minimum coverage per lifecycle role:
  - **Deploy:** role runs twice without changes, systemd unit active, health endpoint reachable.
  - **Backup:** archive + manifest created, manifests list expected files, optional fetch succeeds.
  - **Restore:** validates archive, restores files, service healthy afterwards, supports `restore-check` when available.
  - **Remove:** confirmation guard works, data removal toggles respected, no lingering systemd units.
- When FastDeploy metadata is involved, add a test that validates generated service descriptors (JSON schema, permissions).
- Run focused tests with `just test-role <role>` during development and `just test` before publishing so regressions surface early.

### 5. Wire into ops-control workflows

- Extend `group_vars` when a service needs host-specific defaults that should not be baked into the public role. Typical locations:
  - `group_vars/services/<service>.yml` for service-wide overrides (ports, hostnames, storage paths).
  - `group_vars/hosts/<hostname>.yml` for host-only tweaks (e.g., `backup_root_prefix` on storage boxes).
- Update or create `playbooks/deploy-<service>.yml`, `playbooks/remove-<service>.yml`, etc., if the service needs orchestration beyond the one role (for example, prepping external dependencies).
- Ensure the `just` commands work end-to-end:
  - `just deploy-one <service>`
  - `just backup <service>`
  - `just restore <service> [archive]`
  - `just remove-one <service>`
- If backup/restore is centralized (Echoport exception), explicitly document that `just backup <service>` / `just restore <service>` are not the operator path for that service and link the runbook commands instead.
- Update ops-control docs/runbooks so operators know about the new service.

### 6. Publish and validate

1. Run `just docs-build` and `just docs-serve` inside ops-library to confirm the new role pages appear. Fix warnings immediately so the docs site stays green.
2. Bump the collection version in `galaxy.yml` following semver:
   - **Patch:** bug fixes or doc-only updates.
   - **Minor:** new roles or backward-compatible features.
   - **Major:** breaking changes (variable rename, behavior change).
   Update `CHANGELOG.md` with a short entry describing the service addition.
3. Build and install the collection in ops-control (`just install-local-library`), then re-run the relevant `just` commands for a dry run on staging/VMs. Communicate in ops-control (e.g., Slack #ops or the weekly summary) so downstream users know to reinstall the collection.

## Common pitfalls

- **Missing toctree entries:** role docs will not appear in `docs-build` if you forget to update the relevant `index.md`.
- **No asserts for secrets:** always validate secrets to avoid `CHANGEME` values slipping into production.
- **Hard-coded paths:** use variables (`backup_root_prefix`, `<service>_home`, `fastdeploy_services_root`, etc.) so roles stay portable.
- **Untested restore flows:** a backup without a tested restore is not complete; always add at least one restore test.
- **ops-control gaps:** ensure every capability exposed in metadata has matching `just` recipes and playbooks before calling the service “done”.
- **Capability drift under exceptions:** if backup/restore is handled by Echoport (or another centralized plane), do not leave stale `backup`/`restore` capabilities in metadata.
- **docs-build not run:** skipping the docs build is the fastest way to ship broken navigation. Run it every time.

## Getting This Guide In Front of Contributors

- Link this guide from `CLAUDE.md` (AI context file) so any assistant tasked with “add a new service” reads it before coding.
- Mention it in code reviews and PR templates when services are added.
- Keep it updated whenever you discover a missing step—treat this as the single source of truth for service lifecycle expectations.

By following this checklist each new service gains full lifecycle automation, documentation that ships with the public collection, and predictable hooks in ops-control. That means fewer “fail → analyze → fix → rerun” cycles and faster first-time-success when deploying a new workload.
