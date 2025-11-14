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
```

Operations roles provide consistent snapshot/restore tooling that can be composed with deployment/removal roles to rehearse disaster-recovery scenarios. See `specs/2025-11-11_nyxmon_backup_restore.md` for the Nyxmon design notes.
