# Minecraft Java Restore Role

Restore a Minecraft Java Edition server from a backup archive.

## Description

This role restores the Minecraft server from a Tier 2 backup archive:
1. Stops the minecraft-java service
2. Extracts world data and configuration from archive
3. Sets correct ownership and permissions
4. Restarts the service
5. Waits for server to be ready

## Requirements

- Minecraft Java server previously deployed via `minecraft_java_deploy` role
- Backup archive exists in `/opt/backups/minecraft-java/`
- ansible-core 2.20+

## Role Variables

### Optional Variables

```yaml
minecraft_java_restore_archive: "latest"    # Archive path or "latest"
minecraft_java_restore_dry_run: false       # Preview without making changes
minecraft_java_backup_root: /opt/backups/minecraft-java
minecraft_java_port: 25565                  # For health check after restore
```

## Dependencies

None.

## Example Playbook

```yaml
---
- name: Restore Minecraft Java Server
  hosts: gameserver
  become: true

  roles:
    - role: local.ops_library.minecraft_java_restore
      vars:
        minecraft_java_restore_archive: "latest"
```

Or restore a specific backup:

```yaml
- role: local.ops_library.minecraft_java_restore
  vars:
    minecraft_java_restore_archive: "/opt/backups/minecraft-java/manual-20251128.tar.gz"
```

## Usage with ops-control

```bash
# Restore latest backup
just restore minecraft_java

# Restore specific backup
just restore minecraft_java /opt/backups/minecraft-java/manual-20251128.tar.gz

# Dry-run (preview only)
just restore-check minecraft_java
```

## License

MIT

## Author

ops-library contributors
