# Operations Roles

Backup and restore workflows for long-lived services.

Available runbooks:

- [Home Assistant Backup](https://github.com/ephes/ops-library/blob/main/roles/homeassistant_backup/README.md)
- [Home Assistant Restore](https://github.com/ephes/ops-library/blob/main/roles/homeassistant_restore/README.md)
- [Paperless Backup](https://github.com/ephes/ops-library/blob/main/roles/paperless_backup/README.md)
- [Paperless Restore](https://github.com/ephes/ops-library/blob/main/roles/paperless_restore/README.md)
- [FastDeploy Backup](https://github.com/ephes/ops-library/blob/main/roles/fastdeploy_backup/README.md)
- [FastDeploy Restore](https://github.com/ephes/ops-library/blob/main/roles/fastdeploy_restore/README.md)
- [Nyxmon Backup](https://github.com/ephes/ops-library/blob/main/roles/nyxmon_backup/README.md)
- [Nyxmon Restore](https://github.com/ephes/ops-library/blob/main/roles/nyxmon_restore/README.md)
- [Homelab Backup](https://github.com/ephes/ops-library/blob/main/roles/homelab_backup/README.md)
- [Homelab Restore](https://github.com/ephes/ops-library/blob/main/roles/homelab_restore/README.md)
- [UniFi Backup](https://github.com/ephes/ops-library/blob/main/roles/unifi_backup/README.md)
- [UniFi Restore](https://github.com/ephes/ops-library/blob/main/roles/unifi_restore/README.md)
- [MinIO Backup](https://github.com/ephes/ops-library/blob/main/roles/minio_backup/README.md)
- [MinIO Restore](https://github.com/ephes/ops-library/blob/main/roles/minio_restore/README.md)
- [Navidrome Backup](https://github.com/ephes/ops-library/blob/main/roles/navidrome_backup/README.md)
- [Navidrome Restore](https://github.com/ephes/ops-library/blob/main/roles/navidrome_restore/README.md)
- [Jellyfin Backup](https://github.com/ephes/ops-library/blob/main/roles/jellyfin_backup/README.md)
- [Jellyfin Restore](https://github.com/ephes/ops-library/blob/main/roles/jellyfin_restore/README.md)
- [MeTube Backup](https://github.com/ephes/ops-library/blob/main/roles/metube_backup/README.md)
- [MeTube Restore](https://github.com/ephes/ops-library/blob/main/roles/metube_restore/README.md)
- [Tailscale Backup](https://github.com/ephes/ops-library/blob/main/roles/tailscale_backup/README.md)
- [Tailscale Restore](https://github.com/ephes/ops-library/blob/main/roles/tailscale_restore/README.md)
- [Minecraft Java Backup](https://github.com/ephes/ops-library/blob/main/roles/minecraft_java_backup/README.md)
- [Minecraft Java Restore](https://github.com/ephes/ops-library/blob/main/roles/minecraft_java_restore/README.md)

```{toctree}
:maxdepth: 1

homeassistant_backup
homeassistant_restore
paperless_backup
paperless_restore
fastdeploy_backup
fastdeploy_restore
nyxmon_backup
nyxmon_restore
homelab_backup
homelab_restore
unifi_backup
unifi_restore
minio_backup
minio_restore
navidrome_backup
navidrome_restore
jellyfin_backup
jellyfin_restore
metube_backup
metube_restore
tailscale_backup
tailscale_restore
minecraft_java_backup
minecraft_java_restore
```

Operations roles provide consistent snapshot/restore tooling that can be composed with deployment/removal roles to rehearse disaster-recovery scenarios.
