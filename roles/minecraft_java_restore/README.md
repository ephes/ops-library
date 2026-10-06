# Minecraft Java Restore Role

Restore a Minecraft Java Edition server from a backup archive.

## Disposition

`minecraft_java_restore` is `ad-hoc only`. Echoport is the preferred operator
path for routine Minecraft Java restores. This role remains callable for
break-glass or manual use, but it is not the default operator workflow.

## Description

This role restores the Minecraft server from a Tier 2 backup archive:
1. Extracts the archive to a temp directory and checks that it contains the world
   (also in dry-run mode)
2. Stops the minecraft-java service and confirms it is stopped
3. Copies `server.properties` and the ops/whitelist/ban lists to the safety directory
4. Renames the live world aside and copies the archive's world and files into place
5. Sets correct ownership and permissions and starts the service
6. Waits for the server to be ready

### Safety copies and rollback

- The stop must succeed and the unit must be confirmed `inactive`/`failed`; otherwise the run
  aborts with the live world untouched.
- `server.properties`, `ops.json`, `whitelist.json`, `banned-ips.json` and `banned-players.json`
  are copied to `minecraft_java_restore_safety_root/<UTC timestamp>/files/` (default
  `/var/backups/minecraft-java-pre-restore`). The old `server.properties.<date>~` backup copy is
  no longer written.
- The live world is renamed to `<world>.pre-restore-<UTC timestamp>` next to itself instead of
  being deleted (free on the same filesystem; a world that is a mount point is refused). The
  restored world needs as much free space as the archive's world.
- If any step from the move to the service start fails, the role stops the server, moves the old
  world and files back, starts the server again (only after a successful rollback) and fails
  with the outcome and the safety paths. Files from the archive are copied only when present;
  a failed copy is no longer ignored.
- A successful run deletes older pre-restore copies and keeps only its own; an old copy that is or contains a mount point is never deleted (the run logs it and keeps it); delete it once the
  restored world is verified. The port wait runs after that and does not roll back a slow start.
- The temp directory is removed in an `always` section, also after a failure.

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
minecraft_java_restore_safety_root: /var/backups/minecraft-java-pre-restore
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
