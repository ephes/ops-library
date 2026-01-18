# Removal Roles

Roles for safely removing services and cleaning up resources.

```{toctree}
:maxdepth: 1

fastdeploy_remove
nyxmon_remove
traefik_remove
dns_remove
homeassistant_remove
homelab_remove
unifi_remove
paperless_remove
minio_remove
tailscale_remove
minecraft_java_remove
navidrome_remove
jellyfin_remove
metube_remove
open_webui_remove
open_webui_venv_remove
mastodon_remove
takahe_remove
ollama_remove
```

These roles handle:
- Service停止 and disablement
- Systemd unit removal
- Configuration cleanup
- Optional data preservation
- User and directory removal

Removal roles are idempotent and can be run multiple times safely.
