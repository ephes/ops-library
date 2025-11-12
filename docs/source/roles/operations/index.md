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

Operations roles provide consistent snapshot/restore tooling that can be composed with deployment/removal roles to rehearse disaster-recovery scenarios. See `specs/2025-11-11_nyxmon_backup_restore.md` for the Nyxmon design notes.
