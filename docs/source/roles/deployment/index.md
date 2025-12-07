# Deployment Roles

Roles for deploying and configuring services.

```{toctree}
:maxdepth: 1

fastdeploy_deploy
fastdeploy_self_deploy
nyxmon_deploy
traefik_deploy
dns_deploy
tailscale_deploy
homelab_deploy
homeassistant_deploy
unifi_deploy
paperless_deploy
minio_deploy
minecraft_java_deploy
navidrome_deploy
jellyfin_deploy
metube_deploy
snappymail_deploy
mail_backend_deploy
mail_relay_deploy
certbot_dns_deploy
```

These roles handle the complete deployment lifecycle including:
- Service user and directory setup
- Configuration file management
- Database initialization
- Systemd service configuration
- Reverse proxy integration
- Health checks and validation

Each role supports both rsync (development) and git (production) deployment methods where applicable.
