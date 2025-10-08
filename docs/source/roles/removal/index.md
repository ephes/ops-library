# Removal Roles

Roles for safely removing services and cleaning up resources.

```{toctree}
:maxdepth: 1

fastdeploy_remove
nyxmon_remove
traefik_remove
dns_remove
```

These roles handle:
- Service停止 and disablement
- Systemd unit removal
- Configuration cleanup
- Optional data preservation
- User and directory removal

Removal roles are idempotent and can be run multiple times safely.
