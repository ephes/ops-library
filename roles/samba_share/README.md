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
