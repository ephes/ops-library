# Homelab Remove Role

Ansible role to remove the homelab Django service from a target host.

⚠️ **WARNING:** This role is **DESTRUCTIVE by default**. It will remove the service, user account, home directory, database, and media files unless explicitly overridden.

## Features

- Stops and removes systemd service
- Removes Traefik dynamic configuration
- Removes user account and home directory
- Deletes database and media files (by default)
- Safety checks and confirmation required
- Interactive warning for irreversible data deletion
- Idempotent - safe to run multiple times
- All flags parsed with `| bool` (string `"false"` from `-e` is false)

## Requirements

- Target system: Linux with systemd
- Privileges: root (become: true)
- Ansible: ansible-core 2.20+

## Role Variables

### Service Identification

```yaml
homelab_user: homelab                              # User account name
homelab_home: "/home/{{ homelab_user }}"           # Home directory path
homelab_site_path: "{{ homelab_home }}/site"       # Application directory
```

### File Paths

```yaml
homelab_systemd_unit_path: "/etc/systemd/system/homelab.service"
homelab_traefik_config_path: "/etc/traefik/dynamic/homelab.yml"
```

### Removal Behavior (DESTRUCTIVE DEFAULTS)

```yaml
homelab_remove_user: true              # Remove user account
homelab_remove_home: true              # Remove home directory
homelab_remove_database: true          # Remove SQLite database (IRREVERSIBLE!)
homelab_remove_media: true             # Remove media files (IRREVERSIBLE!)
homelab_remove_traefik_config: true    # Remove Traefik config
```

### Safety Options

```yaml
homelab_remove_confirm: false          # REQUIRED: Must be true for any removal
homelab_remove_auto_confirm: false     # Skip the pause before deleting DB/media
```

## Default Behavior

**By default, this role performs COMPLETE REMOVAL:**

- ✓ Stops and disables systemd service
- ✓ Removes systemd unit file
- ✓ Removes Traefik configuration
- ✓ Deletes SQLite database ⚠️ IRREVERSIBLE
- ✓ Deletes media files ⚠️ IRREVERSIBLE
- ✓ Removes home directory
- ✓ Removes user account

## Preserving Data

The database (`/home/homelab/site/db.sqlite3`) and media (`/home/homelab/site/media`)
live inside the home directory. To keep either of them, also keep the home directory
and the user; the role refuses `homelab_remove_database: false` or
`homelab_remove_media: false` combined with `homelab_remove_home: true` or
`homelab_remove_user: true`. With `homelab_remove_user: true` and
`homelab_remove_home: false` the account is deleted but the home directory stays.

To preserve data, explicitly override the removal flags:

```yaml
- role: local.ops_library.homelab_remove
  vars:
    homelab_remove_confirm: true
    homelab_remove_database: false  # PRESERVE database
    homelab_remove_media: false     # PRESERVE media
    homelab_remove_home: false      # PRESERVE home directory
    homelab_remove_user: false      # PRESERVE user account
```

## Example Playbooks

### Complete Removal (Default)

```yaml
---
- name: Remove Homelab Service (complete)
  hosts: homelab
  become: true
  roles:
    - role: local.ops_library.homelab_remove
      vars:
        homelab_remove_confirm: true
        # All flags default to true - complete removal
        # Database and media will be DELETED (irreversible!)
```

### Preserve All Data

```yaml
---
- name: Remove Homelab Service (preserve data)
  hosts: homelab
  become: true
  roles:
    - role: local.ops_library.homelab_remove
      vars:
        homelab_remove_confirm: true
        # Override defaults to preserve everything
        homelab_remove_database: false
        homelab_remove_media: false
        homelab_remove_home: false
        homelab_remove_user: false
```

### Partial Removal

```yaml
---
- name: Remove Homelab Service (partial)
  hosts: homelab
  become: true
  roles:
    - role: local.ops_library.homelab_remove
      vars:
        homelab_remove_confirm: true
        homelab_remove_user: true       # Remove the account
        homelab_remove_home: false      # But keep /home/homelab
        homelab_remove_database: false  # Not allowed together with user/home removal:
        homelab_remove_media: false     # the role refuses this combination
```

The example above is rejected: keep `homelab_remove_user: false` too, or take a
backup first and let the role delete everything.

## Safety Features

### Confirmation Required

The role will fail if `homelab_remove_confirm` is not explicitly set to `true`:

```
❌ REMOVAL BLOCKED: homelab_remove_confirm must be set to true
```

### Removal Plan Display

Before any removal, the role displays exactly what will be removed and preserved:

```
═══════════════════════════════════════════════════════════════
🗑️  HOMELAB REMOVAL PLAN
═══════════════════════════════════════════════════════════════

Systemd service: /etc/systemd/system/homelab.service
Traefik config: /etc/traefik/dynamic/homelab.yml (remove)
Database: /home/homelab/site/db.sqlite3 ⚠️  IRREVERSIBLE!
Media files: /home/homelab/site/media/ ⚠️  IRREVERSIBLE!
Home directory: /home/homelab (remove)
User account: homelab (remove)

═══════════════════════════════════════════════════════════════
```

### Interactive Confirmation

If an existing database or media directory will be deleted, the role pauses for
manual confirmation unless `homelab_remove_auto_confirm` is true (`"false"` passed
with `-e` keeps the pause):

```
⚠️  WARNING: DATABASE AND/OR MEDIA WILL BE PERMANENTLY DELETED ⚠️

This operation is IRREVERSIBLE. Run `just backup homelab` (or trigger the
Echoport `homelab` target) before continuing ...

Press ENTER to continue with removal, or Ctrl+C to abort.
```

### Idempotency

The role is safe to run multiple times. It checks for the existence of each component before attempting removal.

## Tags

You can use tags to run specific parts of the removal:

```bash
# Run only validation
ansible-playbook playbook.yml --tags homelab_remove_validation

# Remove service only
ansible-playbook playbook.yml --tags homelab_remove_service

# Remove Traefik config only
ansible-playbook playbook.yml --tags homelab_remove_traefik

# Remove user and data only
ansible-playbook playbook.yml --tags homelab_remove_user
```

## Testing

### Test Complete Removal

```bash
# Deploy homelab
cd ops-control
just deploy-one homelab

# Verify deployment
ssh your-server "systemctl status homelab"

# Remove with defaults (complete removal)
just remove-one homelab

# Verify everything removed
ssh your-server "systemctl status homelab"  # Should fail
ssh your-server "id homelab"                # Should fail
ssh your-server "ls /home/homelab"          # Should fail
```

### Test Data Preservation

Modify `ops-control/playbooks/remove-homelab.yml` to preserve data:

```yaml
homelab_remove_database: false
homelab_remove_media: false
homelab_remove_home: false
homelab_remove_user: false
```

Then:

```bash
# Remove service
just remove-one homelab

# Verify partial removal
ssh your-server "systemctl status homelab"  # Should fail (service removed)
ssh your-server "id homelab"                # Should succeed (user preserved)
ssh your-server "ls /home/homelab/site/db.sqlite3"  # Should succeed (DB preserved)

# Re-deploy (should use existing data)
just deploy-one homelab
```

## Dependencies

None.

## License

MIT

## Author Information

Part of the ops-library collection for homelab infrastructure automation.
