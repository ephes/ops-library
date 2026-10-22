# Docker cache cleanup

Schedule Docker build cache cleanup on an existing systemd Docker host. This role
installs no packages and changes no Docker daemon configuration.

By default, the daily job removes build cache unused for seven days, including internal and
frontend cache. It does not prune images, containers, networks or volumes. Builds
may need to download dependencies and recompute layers afterward. Recently used
cache is preserved in age-only mode; the optional size pass can evict it.
Neither mode imposes a filesystem quota. Docker protects cache
in use by active builds. Do not remove containerd snapshot directories manually.

## Requirements

An existing Docker Engine at `/usr/bin/docker`, with `docker builder prune`
supporting `--all`, `--force` and `--filter until`, and systemd. Run as root.
For a positive size target, the buildx plugin must also support `prune` with
`--max-used-space` and `--reserved-space`.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `docker_cache_cleanup_enabled` | `true` | Enable the timer; false stops/disables an existing timer but retains its unit files |
| `docker_cache_cleanup_unused_hours` | `168` | Positive whole hours since cache was last used |
| `docker_cache_cleanup_max_used_bytes` | `0` | Optional size target in bytes; zero keeps age-only cleanup. A separate size pass can evict recently used build cache. |
| `docker_cache_cleanup_calendar` | `*-*-* 03:30:00` | systemd calendar in the host timezone |
| `docker_cache_cleanup_randomized_delay` | `30m` | Spread runs over this interval |

## Example

```yaml
- hosts: docker_hosts
  become: true
  roles:
    - role: local.ops_library.docker_cache_cleanup
      docker_cache_cleanup_unused_hours: 168
      docker_cache_cleanup_max_used_bytes: 10000000000
      docker_cache_cleanup_calendar: "*-*-* *:00/15:00"
      docker_cache_cleanup_randomized_delay: "1m"
```

The persistent timer catches up after downtime and can run shortly after enabling
it if a scheduled run was missed. Deploying the role does not explicitly start the
cleanup service. Set `docker_cache_cleanup_enabled: false` and redeploy to disable
future runs; an already running cleanup finishes normally.

## Operations

```bash
systemctl list-timers docker-cache-cleanup.timer
journalctl -u docker-cache-cleanup.service
systemctl start docker-cache-cleanup.service  # manual run, same age filter
systemctl stop docker-cache-cleanup.timer     # temporary pause
```

Redeploy to resume a temporarily paused timer. Check root usage with `df -h /` and
`docker system df`; Docker cache/image figures share layers and are not additive.

With a positive size target, a second command prunes the default buildx builder
without the age filter and with zero reserved cache. An age filter on that pass
would leave large dependency chains behind recently used leaves. This requires
buildx with `--max-used-space` and `--reserved-space`; the role checks support
before modifying units. Shared records and active builds can prevent immediately
meeting the target; usage can temporarily exceed it between runs. Runtime images,
containers and volumes remain outside this cleanup. A 10 GB cache target does not
mean the Docker installation itself fits within 10 GB.
