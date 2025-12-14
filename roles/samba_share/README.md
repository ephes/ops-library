# samba_share

Generic Samba share role.

- Installs Samba if needed.
- Creates a share snippet in `/etc/samba/smb.conf.d/<name>.conf`.
- Ensures `smb.conf` includes the snippet explicitly (no glob expansion required).

## Variables

Required:

- `samba_share_name`: Share name.
- `samba_share_path`: Path to export.

Common options:

- `samba_share_read_only` (bool, default `false`)
- `samba_share_browseable` (bool, default `true`)
- `samba_share_guest_ok` (bool, default `false`)
- `samba_share_valid_users` (list, default `[]`)
- `samba_share_extra_options` (dict, default `{}`)
- `samba_share_users` (list, default `[]`): Samba users to create (each item: `{name, password}`).
- `samba_share_manage_system_users` (bool, default `true`): Ensure matching Unix users exist for `samba_share_users`.
- `samba_share_system_group` (string, default `sambashare`): Unix group for the created users.

Filesystem permissions (optional, only applied if set):

- `samba_share_path_owner` (string, default `""`): Owner of the share directory.
- `samba_share_path_group` (string, default `""`): Group of the share directory.
- `samba_share_path_mode` (string, default `""`): Mode of the share directory (e.g., `"0770"`).

## Example

```yaml
- name: Expose fast files share
  hosts: fractal
  become: true
  roles:
    - role: local.ops_library.samba_share
      vars:
        samba_share_name: fast
        samba_share_path: /fast/general
        samba_share_valid_users: [jochen]
        samba_share_read_only: false
```
