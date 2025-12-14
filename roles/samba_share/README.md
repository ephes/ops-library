# samba_share

Generic Samba share role for exposing directories over SMB/CIFS.

## Features

- Installs Samba packages if needed
- Creates a share snippet in `/etc/samba/smb.conf.d/<name>.conf`
- Ensures `smb.conf` includes the snippet explicitly (no glob expansion)
- Optionally creates Samba users and Unix accounts
- Optionally sets filesystem ownership and permissions on share directories

## Requirements

- Ubuntu/Debian target host
- Root/become access

## Variables

### Required

| Variable | Description |
|----------|-------------|
| `samba_share_name` | Share name as it appears in Finder/Windows |
| `samba_share_path` | Filesystem path to export |

### Access Control

| Variable | Default | Description |
|----------|---------|-------------|
| `samba_share_read_only` | `false` | Make share read-only |
| `samba_share_browseable` | `true` | Show share in network browser |
| `samba_share_guest_ok` | `false` | Allow anonymous access |
| `samba_share_valid_users` | `[]` | List of allowed usernames |

### Samba Permissions (applied to new files/directories)

| Variable | Default | Description |
|----------|---------|-------------|
| `samba_share_create_mask` | `0660` | Permissions for new files |
| `samba_share_directory_mask` | `0770` | Permissions for new directories |
| `samba_share_force_user` | `""` | Force file ownership to this user |
| `samba_share_force_group` | `""` | Force file ownership to this group |

### Filesystem Permissions (on share directory itself)

| Variable | Default | Description |
|----------|---------|-------------|
| `samba_share_path_owner` | `""` | Owner of share directory |
| `samba_share_path_group` | `""` | Group of share directory |
| `samba_share_path_mode` | `""` | Mode of share directory (e.g., `"0770"`) |

### User Management

| Variable | Default | Description |
|----------|---------|-------------|
| `samba_share_users` | `[]` | Samba users to create: `[{name, password}]` |
| `samba_share_manage_system_users` | `true` | Create Unix users for Samba users |
| `samba_share_system_group` | `sambashare` | Unix group for created users |

### Additional Options

| Variable | Default | Description |
|----------|---------|-------------|
| `samba_share_extra_options` | `{}` | Dict of extra smb.conf options |

## Examples

### Basic single share

```yaml
- name: Expose fast files share
  hosts: myserver
  become: true
  roles:
    - role: local.ops_library.samba_share
      vars:
        samba_share_name: fast
        samba_share_path: /fast/general
        samba_share_valid_users: [jochen]
        samba_share_read_only: false
```

### Multiple shares with inventory configuration

Define shares in `host_vars/myserver.yml`:

```yaml
my_samba_shares:
  - name: photos
    path: /tank/photos
    valid_users: [jochen]
    read_only: false
    browseable: true
    guest_ok: false
    path_owner: jochen
    path_group: jochen
    path_mode: "0770"

  - name: media
    path: /tank/media
    valid_users: [jochen]
    read_only: false
    browseable: true
    guest_ok: false
    path_owner: jochen
    path_group: jochen
    path_mode: "0770"

  - name: backups
    path: /tank/backups
    valid_users: [jochen]   # Restricted to specific user
    read_only: false
    browseable: true
    guest_ok: false         # No anonymous access
    path_owner: jochen
    path_group: jochen
    path_mode: "0770"       # Only owner/group can access
```

Deploy with a playbook:

```yaml
- name: Deploy Samba shares
  hosts: myserver
  become: true
  tasks:
    - name: Configure Samba shares
      ansible.builtin.include_role:
        name: local.ops_library.samba_share
      loop: "{{ my_samba_shares }}"
      loop_control:
        loop_var: share
        label: "{{ share.name }}"
      vars:
        samba_share_name: "{{ share.name }}"
        samba_share_path: "{{ share.path }}"
        samba_share_valid_users: "{{ share.valid_users | default([]) }}"
        samba_share_read_only: "{{ share.read_only | default(false) }}"
        samba_share_browseable: "{{ share.browseable | default(true) }}"
        samba_share_guest_ok: "{{ share.guest_ok | default(false) }}"
        samba_share_path_owner: "{{ share.path_owner | default('') }}"
        samba_share_path_group: "{{ share.path_group | default('') }}"
        samba_share_path_mode: "{{ share.path_mode | default('') }}"
```

### Restricted share (e.g., backups)

To restrict a share to specific users:

```yaml
samba_share_name: backups
samba_share_path: /tank/backups
samba_share_valid_users: [jochen]  # Only jochen can access
samba_share_guest_ok: false         # Deny anonymous access
samba_share_path_owner: jochen
samba_share_path_group: jochen
samba_share_path_mode: "0770"       # Only owner/group at filesystem level
```

This enforces access at three levels:
1. **Samba `valid users`**: Only listed users can authenticate
2. **Samba `guest ok = no`**: Anonymous access denied
3. **Filesystem permissions**: Mode `0770` with owner `jochen` restricts filesystem access

## Access Verification

### From macOS

```bash
# Connect via Finder: Cmd+K → smb://server.local/sharename
# Or via terminal:
smbutil view //user@server.local
mount_smbfs //user@server.local/share /mnt/point
```

### From Windows

```cmd
# In File Explorer address bar:
\\server.local\sharename
# Or map network drive via GUI
```

### On the server

```bash
# Verify config
testparm -s

# Check active connections
smbstatus -b

# Verify filesystem permissions
ls -la /path/to/share
```

## Dependencies

None.

## License

MIT
