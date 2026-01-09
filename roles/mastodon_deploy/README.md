# Mastodon Deploy Role

Deploys Mastodon from source with rbenv + nvm runtimes, systemd services, and Traefik routing. The role provisions PostgreSQL via `postgres_install` and can optionally install Redis via `redis_install` when `mastodon_redis_manage: true`. It supports rsync (dev) or git (staging/production) deployment modes.

## Features

- Installs Mastodon into `/home/mastodon/live` (configurable via `mastodon_site_path`) with rbenv + nvm runtimes.
- Generates `.env.production` from the shared defaults.
- Runs database migrations and asset precompile tasks.
- Configures systemd units: `mastodon-web`, `mastodon-sidekiq`, `mastodon-streaming`.
  - Streaming uses `node ./streaming` (Mastodon no longer ships `bin/streaming`).
- Runs a local nginx proxy for static assets and upstream routing.
- Writes Traefik dynamic config for HTTPS routing (to nginx by default).
  - Removes legacy Traefik config at `{{ mastodon_traefik_legacy_config_path }}` when `mastodon_remove_legacy_traefik_config: true`.
- Optionally installs the Mastodon maintenance timer via `mastodon_maintenance_enabled`.

## Requirements

- Ubuntu/Debian host with systemd
- Traefik running when `mastodon_traefik_enabled: true`
- Outbound network access to fetch rbenv/nvm and the Mastodon repository (when using git mode)

## Required Variables

```yaml
mastodon_local_domain: "example.com"
mastodon_web_domain: "social.example.com"
mastodon_secret_key_base: "..."
mastodon_otp_secret: "..."
mastodon_vapid_public_key: "..."
mastodon_vapid_private_key: "..."
mastodon_active_record_encryption_primary_key: "..."
mastodon_active_record_encryption_deterministic_key: "..."
mastodon_active_record_encryption_key_derivation_salt: "..."
mastodon_postgres_password: "..."
mastodon_smtp_server: "smtp.example.com"
mastodon_smtp_port: 587
mastodon_smtp_login: "user@example.com"
mastodon_smtp_password: "..."
mastodon_smtp_from_address: "Mastodon <noreply@example.com>"
mastodon_smtp_domain: "example.com"
```

If you prefer a single-domain setup, set `mastodon_domain` and leave `mastodon_local_domain` / `mastodon_web_domain` unset.

## Generating secrets

From the Mastodon source directory (as the `mastodon` user), generate secrets and store them in ops-control:

```bash
cd /home/mastodon/live
bundle exec rake secret  # SECRET_KEY_BASE
bundle exec rake secret  # OTP_SECRET
bundle exec rake mastodon:webpush:generate_vapid_key
```

Deployment mode:

```yaml
# rsync (local dev)
mastodon_source_mode: rsync
mastodon_source_path: "/path/to/mastodon"

# git (staging/prod)
mastodon_source_mode: git
mastodon_git_repo: "https://github.com/mastodon/mastodon.git"
mastodon_git_ref: "main"
```

## Common Configuration

```yaml
mastodon_web_port: 10040
mastodon_streaming_port: 10041
mastodon_sidekiq_concurrency: 25
mastodon_db_pool: 25
mastodon_maintenance_enabled: true
mastodon_traefik_enabled: true
mastodon_traefik_host: "{{ mastodon_web_domain }}"
mastodon_nginx_enabled: true
mastodon_nginx_port: 10044
mastodon_nginx_cache_enabled: false
mastodon_runtime_chown_recursive: false
```

The role keeps ownership in sync for runtime directories listed in
`mastodon_runtime_chown_paths`. Set `mastodon_runtime_chown_recursive: true`
if you need to repair ownership on existing content (for example after a
root-owned rsync), but note this can be slow on large media trees.

Split-domain deployments are supported and intentional: `LOCAL_DOMAIN` (handles) can differ from `WEB_DOMAIN` (UI). Do not change `LOCAL_DOMAIN` after federation begins.

## Redis

By default, the role assumes an existing local Redis instance (`127.0.0.1:6379` with no password). To install Redis with ops-library, set:

```yaml
mastodon_redis_manage: true
```

## nginx proxy

nginx listens on `127.0.0.1:{{ mastodon_nginx_port }}` and serves static assets from `{{ mastodon_public_path }}` while
proxying app traffic to Puma and the streaming service. Traefik routes to nginx when `mastodon_nginx_enabled: true`.
Set `mastodon_nginx_user`/`mastodon_nginx_group` to run as root if you want to match the legacy host setup.
Enable proxy caching for `/system/` by setting `mastodon_nginx_cache_enabled: true`. nginx logs are rotated via
`{{ mastodon_nginx_logrotate_path }}` when `mastodon_nginx_logrotate_enabled: true`.

## SMTP validation

SMTP settings are required by default. Set `mastodon_require_smtp: false` to skip SMTP validation for dev/staging runs
that do not send email.

## Runtime versions

By default, the role reads `.ruby-version` and `.nvmrc` from the Mastodon repository. If you override
`mastodon_ruby_version` or `mastodon_node_version`, make sure they meet the upstream requirements for
your Mastodon release (for example, v4.5.3 requires Ruby 3.2+ and Node 20.19+; confirm via release notes).
Set `mastodon_ruby_build_update: false` if you need to pin the ruby-build plugin to its current revision.

See `defaults/main.yml` and `roles/mastodon_shared/defaults/main.yml` for the full variable reference.

## Yarn / Corepack

Mastodon pins Yarn via the `packageManager` field, so the role enables Node's corepack shim by default and
uses `yarn install --immutable`. If you prefer a global Yarn install, set `mastodon_yarn_use_corepack: false`
and `mastodon_yarn_global_install: true`, then adjust `mastodon_yarn_flags` to a compatible value.

## Jemalloc

Ruby builds default to `RUBY_CONFIGURE_OPTS="-with-jemalloc"` and services set `LD_PRELOAD=libjemalloc.so`.
Override `mastodon_ruby_configure_opts` or `mastodon_ld_preload` to change this behavior.

## Health check

The default health check hits `http://127.0.0.1:<web_port>/api/v1/instance` after deploy and sets a `Host` header
matching `mastodon_web_domain` (or `mastodon_local_domain`). Override with `mastodon_healthcheck_url` /
`mastodon_healthcheck_headers`, or disable with `mastodon_healthcheck_enabled: false`.

## Legacy systemd units

The role disables legacy underscore unit names (`mastodon_web`, `mastodon_sidekiq`, `mastodon_streaming`) by default
to prevent port conflicts. Set `mastodon_disable_legacy_services: false` or override `mastodon_legacy_service_names`
to keep them running.

## Dependencies

- `local.ops_library.mastodon_shared`
- `local.ops_library.postgres_install`
- `local.ops_library.redis_install` (optional when `mastodon_redis_manage: true`)

## Example Playbook

```yaml
- hosts: mastodon
  become: true
  vars:
    mastodon_local_domain: "example.com"
    mastodon_web_domain: "social.example.com"
    mastodon_secret_key_base: "{{ mastodon_secret_key_base }}"
    mastodon_otp_secret: "{{ mastodon_otp_secret }}"
    mastodon_vapid_public_key: "{{ mastodon_vapid_public_key }}"
    mastodon_vapid_private_key: "{{ mastodon_vapid_private_key }}"
    mastodon_postgres_password: "{{ mastodon_postgres_password }}"
    mastodon_source_mode: git
    mastodon_git_repo: "https://github.com/mastodon/mastodon.git"
    mastodon_git_ref: "main"
  roles:
    - role: local.ops_library.mastodon_deploy
```

## Handlers

- `reload systemd`
- `restart mastodon-web`
- `restart mastodon-sidekiq`
- `restart mastodon-streaming`
- `reload traefik`

## Testing

```bash
cd /path/to/ops-library
just test-role mastodon_deploy
```

## License

MIT
