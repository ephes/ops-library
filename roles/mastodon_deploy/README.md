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

- Ubuntu or Debian 12/13 host with systemd
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
mastodon_nginx_federation_cache_enabled: false
mastodon_nginx_access_log_timing: false
mastodon_runtime_chown_recursive: false
mastodon_clear_rails_cache_on_deploy: true
```

### Process sizing

`mastodon_web_concurrency` (Puma workers, `WEB_CONCURRENCY`, default `2`; `0` runs Puma in single mode),
`mastodon_max_threads` (Puma threads per worker, `MAX_THREADS`, default `5`), `mastodon_sidekiq_concurrency`
(`sidekiq -c`, default `25`) and `mastodon_db_pool` (`DB_POOL`, default `25`) size the processes. `DB_POOL` is shared
by Puma and Sidekiq, so the role refuses a pool smaller than either the Sidekiq concurrency or the Puma thread count.
A small single-user instance runs fine with one Puma worker, Sidekiq concurrency 5 and a pool of 5; raise Sidekiq
concurrency (and the pool with it) if the Sidekiq queues stop draining.

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
`{{ mastodon_nginx_logrotate_path }}` when `mastodon_nginx_logrotate_enabled: true`. POST request bodies (media
uploads, federation inbox) are buffered via `client_body_temp_path` at `{{ mastodon_nginx_body_temp_path }}`
(default `/var/lib/mastodon-nginx/body`), owned by the nginx service user.

### Federation document cache

`mastodon_nginx_federation_cache_enabled: true` caches the public documents listed in
`mastodon_nginx_federation_cache_locations` (exact paths; default `/actor`, `/.well-known/webfinger`,
`/.well-known/host-meta`, `/.well-known/nodeinfo`, `/nodeinfo/2.0`) in a separate cache zone at
`mastodon_nginx_federation_cache_path`.

- nginx follows Mastodon's own `Cache-Control`. Mastodon marks these responses public: instance actor 10
  minutes, WebFinger, host-meta and the NodeInfo discovery document 3 days, NodeInfo 30 minutes, WebFinger
  errors 3 minutes. Responses that are private, set a cookie or carry no caching headers are not stored.
- Mastodon's `Vary: Accept, Origin` is ignored, because every distinct `Accept` string from remote software
  would be a separate, cold entry. Instead the cache key is the forwarded scheme and host, the full request
  URI, `Accept` reduced to the formats Mastodon tells apart (ActivityStreams JSON, JRD, XRD/XML, other JSON,
  HTML, none) and whether the request carries `Origin` (Mastodon adds `Access-Control-Allow-Origin: *` only
  then). Puma receives the reduced `Accept` and no `Accept-Encoding`, so a cached body always matches its key;
  nginx compresses for the client.
- Concurrent misses for the same entry wait for the one request filling it, for up to
  `mastodon_nginx_federation_cache_lock_timeout` (default `10s`, used for both `proxy_cache_lock_timeout` and
  `proxy_cache_lock_age`); after that they go to Puma themselves. An expired entry is still served while nginx
  refreshes it in the background, and also when Puma fails or times out; entries are removed only after
  `mastodon_nginx_federation_cache_inactive` (default `7d`) without use.
- After the health check the role fills the cache for every host in
  `mastodon_nginx_federation_cache_prime_hosts` (default the Traefik host) and every entry in
  `mastodon_nginx_federation_cache_prime` plus `mastodon_nginx_federation_cache_prime_extra` (path and
  `Accept`; default `/actor`, host-meta and both NodeInfo documents), then requests each again and fails the
  deploy unless it is served from the cache.
- Why: when a post reaches many servers at once, GoToSocial servers verify Mastodon's signed key fetch by
  fetching `/actor` back while every Puma thread is busy with their own signed requests. A cached `/actor` is
  answered by nginx without a Puma thread; a missing one waits for Mastodon's 10 s outbound read timeout.
- Limitation: the cache only helps while the entry exists. After a purge, after eviction (`_inactive` without
  any request, or `_size` exceeded) or for an `Accept` bucket that was never requested, the first request
  needs a free Puma thread again; during a burst that can still block until the timeout. Redeploying (or
  requesting the documents once) refills it.
- Responses carry `X-Cache-Status` (`MISS`, `HIT`, `STALE`, `UPDATING`, ...). Status and account documents
  are deliberately not cached: they depend on the requester (blocks, visibility).
- To drop cached entries (for example after changing the instance actor), remove the files under
  `mastodon_nginx_federation_cache_path`, reload `mastodon-nginx` and redeploy to refill the cache.

`mastodon_nginx_access_log_timing: true` appends `rt=$request_time urt=$upstream_response_time
cache=$upstream_cache_status` to the combined access log format; the existing fields keep their positions.
`mastodon_nginx_limit_nofile` (default `65536`) sets `LimitNOFILE` for the nginx unit so that
`mastodon_nginx_worker_connections` (default `4096`) fits under the open-file limit.

## SMTP validation

SMTP settings are required by default. Set `mastodon_require_smtp: false` to skip SMTP validation for dev/staging runs
that do not send email.

## Runtime versions

By default, the role reads `.ruby-version` and `.nvmrc` from the Mastodon repository. If you override
`mastodon_ruby_version` or `mastodon_node_version`, make sure they meet the upstream requirements for
your Mastodon release. For example, Mastodon v4.6.3 ships `.ruby-version` `4.0.5` and `.nvmrc` `24.17`;
if you override them, make sure they still meet the upstream minimums for that release (Ruby 3.3+ and
Node 22+ as of 4.6; confirm via release notes).
Set `mastodon_ruby_build_update: false` if you need to pin the ruby-build plugin to its current revision.

Because the version is read from the tag, upgrading Mastodon can change the Ruby or Node version. When it
does, rbenv compiles the new Ruby from source (tens of minutes) and every native gem is rebuilt into a
fresh `vendor/bundle/ruby/<abi>/` tree. The previous Ruby install and gem tree are left in place, so budget
disk accordingly. Upgrading v4.5.9 to v4.6.3 crosses a Ruby major (3.4.7 to 4.0.5).

See `defaults/main.yml` and `roles/mastodon_shared/defaults/main.yml` for the full variable reference.

When source, runtime, dependency, migration, or asset-build tasks change, the role clears Rails cache by default
before the post-deploy health check. This avoids stale cached instance metadata surviving in Redis across
upgrades. Set `mastodon_clear_rails_cache_on_deploy: false` if you need to keep warm caches during deploys.

## Media processing

Mastodon 4.6 dropped ImageMagick support and requires libvips, so `mastodon_system_packages` installs
`libvips-dev` and `libvips-tools`. `imagemagick` is still installed as well so that pre-4.6 refs remain
deployable; it can be dropped once no host deploys a ref older than 4.6. Mastodon 4.6 also requires
FFmpeg 5.1+. The distribution `ffmpeg` package meets that minimum on Debian 12 (5.1.x) and Ubuntu 24.04
(6.1.x), but note that on Ubuntu `ffmpeg` lives in `universe`, which receives only best-effort security
support — track FFmpeg CVEs separately there rather than assuming `apt upgrade` covers them.

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
- `clear mastodon cache`
- `restart mastodon-web`
- `restart mastodon-sidekiq`
- `restart mastodon-streaming`
- `restart mastodon-nginx`
- `reload traefik`

## Testing

```bash
cd /path/to/ops-library
just test-role mastodon_deploy
```

## License

MIT
