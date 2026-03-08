# ssh_authorized_keys_manage

Manage `~/.ssh` and `authorized_keys` for an existing target account, including `root`.

## What it does

- Validates the role configuration before changing the host.
- Ensures the target account's `~/.ssh` directory exists with mode `0700`.
- Renders the complete `authorized_keys` file with mode `0600`.
- Supports per-key `key_options`.
- Fails clearly when key management is enabled but no keys are configured.
- Adds a `Managed by Ansible` comment at the top of the file.

## Why this role renders the whole file

This role writes the full `authorized_keys` file from a template instead of looping over `ansible.posix.authorized_key`.

- Per-key `key_options` and optional comments stay easy to express in one list.
- Ownership and file mode are managed explicitly in the same place.
- Full-file rendering avoids the `authorized_key` loop + `exclusive` footgun, where each iteration can remove keys written by prior iterations.

This role is intended for cases where the playbook owns the complete `authorized_keys` file for the target account.

## Requirements

- The target user, group, and home directory must already exist.
- Run the role with privileges that can write the target account's home directory.

## Role Variables

| Variable | Default | Description |
| --- | --- | --- |
| `ssh_authorized_keys_manage_enabled` | `true` | Enable or skip the role. |
| `ssh_authorized_keys_manage_user` | `root` | Target account owner for `~/.ssh` and `authorized_keys`. |
| `ssh_authorized_keys_manage_group` | `{{ ssh_authorized_keys_manage_user }}` | Group owner for `~/.ssh` and `authorized_keys`. |
| `ssh_authorized_keys_manage_home` | `/root` for `root`, otherwise `/home/<user>` | Target account home directory. Override when the account lives elsewhere. |
| `ssh_authorized_keys_manage_entries` | `[]` | Authorized key entries to render into the file. Must be non-empty when the role is enabled. |

## Authorized Key Entry Schema

Each item in `ssh_authorized_keys_manage_entries` supports:

| Field | Required | Description |
| --- | --- | --- |
| `key` | yes | Public key material. Usually `ssh-ed25519 AAAA...` or another OpenSSH public key line without key options. |
| `comment` | no | Optional trailing comment appended after `key`. |
| `key_options` | no | Optional OpenSSH `authorized_keys` options prepended before `key`. |

Notes:

- If your `key` value already includes a trailing comment, leave `comment` unset.
- The role manages the complete file contents. Keys not present in `ssh_authorized_keys_manage_entries` are removed from the rendered file.

## Examples

Authorize two keys for `root`:

```yaml
- name: Manage root SSH access
  hosts: all
  become: true
  roles:
    - role: local.ops_library.ssh_authorized_keys_manage
      vars:
        ssh_authorized_keys_manage_user: root
        ssh_authorized_keys_manage_group: root
        ssh_authorized_keys_manage_home: /root
        ssh_authorized_keys_manage_entries:
          - key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBASE64KEYFOROPS1"
            comment: "opsgate@runner"
          - key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBASE64KEYFOROPS2"
            key_options: 'from="100.64.0.0/10",no-agent-forwarding'
            comment: "break-glass"
```

Manage a non-root account with a custom home directory:

```yaml
- name: Manage deploy user SSH access
  hosts: all
  become: true
  roles:
    - role: local.ops_library.ssh_authorized_keys_manage
      vars:
        ssh_authorized_keys_manage_user: deploy
        ssh_authorized_keys_manage_group: deploy
        ssh_authorized_keys_manage_home: /srv/deploy
        ssh_authorized_keys_manage_entries:
          - key: "{{ lookup('file', '~/.ssh/deploy.pub') }}"
```
