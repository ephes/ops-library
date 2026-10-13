# Minecraft Java Restore Role

Restore a Minecraft Java Edition server from a backup archive.

## Disposition

`minecraft_java_restore` is `ad-hoc only`. Echoport is the preferred operator
path for routine Minecraft Java restores. This role remains callable for
break-glass or manual use, but it is not the default operator workflow.

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

## Retained pre-restore copies

Before replacing live data, the shared `restore_preserve_internal` tasks retain
a timestamped sibling. Ordinary directories are atomically renamed away; mount
points are copied with `cp -a` and verified by checksum and metadata before
emptying their contents. Insufficient space fails before live data changes.
Nested mounts and symlink targets are refused. Quiesce all writers and run only
one restore at a time; when service stopping is disabled, quiescing is the caller’s responsibility.

The final report prints the retained path and size in bytes. Restores **never
remove or prune these copies**, including on failure or a later restore. The
owner prunes old copies by hand after inspecting them. Exact path patterns:

- `{{ minecraft_java_server_dir }}/{{ minecraft_java_world_name }}.pre-restore-*`

Each `*` is a UTC timestamp plus a random suffix. Failed copy verification may
leave an incomplete sibling; inspect it manually. On failure, use the reported
copy to recover before starting services.

When the systemd unit is genuinely absent and inactive, world data can be restored before
deploy. Units installed in vendor paths or supplied with a `.service` suffix
are detected by systemd and must stop successfully, then are started again
after restore. A missing unit that still has a running process is refused. Masked or failed load states
abort rather than allowing writes into the retained copy.
