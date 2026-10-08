# Docker cache cleanup

Schedule Docker build cache cleanup on an existing systemd Docker host. This role
installs no packages and changes no Docker daemon configuration.

The daily job removes build cache unused for seven days, including internal and
frontend cache. It does not prune images, containers, networks or volumes. Builds
may need to download dependencies and recompute layers afterward. Recently used
cache is preserved; the age filter is not a hard disk quota. Docker protects cache
in use by active builds. Do not remove containerd snapshot directories manually.

## Requirements

An existing Docker Engine at `/usr/bin/docker`, with `docker builder prune`
supporting `--all`, `--force` and `--filter until`, and systemd. Run as root.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `docker_cache_cleanup_enabled` | `true` | Enable the timer; false stops/disables an existing timer but retains its unit files |
| `docker_cache_cleanup_unused_hours` | `168` | Positive whole hours since cache was last used |
| `docker_cache_cleanup_calendar` | `*-*-* 03:30:00` | systemd calendar in the host timezone |
| `docker_cache_cleanup_randomized_delay` | `30m` | Spread runs over this interval |

## Example

```yaml
- hosts: docker_hosts
  become: true
  roles:
    - role: local.ops_library.docker_cache_cleanup
      docker_cache_cleanup_unused_hours: 168
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
