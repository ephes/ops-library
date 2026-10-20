# ssh_authorized_keys_manage

Manage `~/.ssh` and `authorized_keys` for an existing target account, including `root`.

## What it does

- Validates the role configuration before changing the host.
- Ensures the target account's `~/.ssh` directory exists with mode `0700`.
- Renders the complete `authorized_keys` file with mode `0600` (default), or,
  with `ssh_authorized_keys_manage_exclusive: false`, adds or updates only the
  listed entries and leaves every other line of the file alone.
- Supports per-key `key_options`.
- Fails clearly when key management is enabled but no keys are configured.
- Adds a `Managed by Ansible` comment at the top of the file.

## Why this role renders the whole file

This role writes the full `authorized_keys` file from a template instead of looping over `ansible.posix.authorized_key`.

- Per-key `key_options` and optional comments stay easy to express in one list.
- Ownership and file mode are managed explicitly in the same place.
- Full-file rendering avoids the `authorized_key` loop + `exclusive` footgun, where each iteration can remove keys written by prior iterations.

Use the default only where the playbook owns the complete `authorized_keys` file for the target account.

## Non-exclusive mode

When other roles or people also add keys to the same file (for example a
forced-command key that a service role installs for `root`), set
`ssh_authorized_keys_manage_exclusive: false`. The role then runs
`ansible.posix.authorized_key` once per entry with `state: present` and
`exclusive: false`:

- each entry is matched by its key material (type and base64 blob);
- a key that is missing is appended at the end of the file;
- a key that is present with other options or another comment is rewritten in
  place to the declared line;
- every key that is not listed stays, and so do comment lines.
- before it touches the real file, the role rehearses on scratch copies with
  the module itself: adding an unrelated probe key must leave every existing
  byte as it was, and applying the entries must leave every declared line in
  the result. Otherwise it fails and changes nothing. That refuses files the
  module would rewrite (lines sharing a key, repeated identical comment or
  blank lines, key lines without a comment or with runs of spaces, CRLF line
  ends) and entries that share a key.

The declared line is the same one the default mode renders
(`<key_options> <key> <comment>`), so switching an existing file from the
default mode to non-exclusive mode is a no-op for the listed keys, as long as
every line has a comment: the module writes a key without a comment with a
trailing space, so a file with comment-less lines the default mode rendered is
refused (see below). Entries without a comment work; the module writes them
with that trailing space.

Trade-off: a key you remove from `ssh_authorized_keys_manage_entries` is no
longer removed from the host. Remove it explicitly, for example with an
`ansible.posix.authorized_key` task with `state: absent` for that key.

## Requirements

- The target user, group, and home directory must already exist.
- Run the role with privileges that can write the target account's home directory.
- Debian 12 and 13 are declared supported platforms.

## Role Variables

| Variable | Default | Description |
| --- | --- | --- |
| `ssh_authorized_keys_manage_enabled` | `true` | Enable or skip the role. |
| `ssh_authorized_keys_manage_user` | `root` | Target account owner for `~/.ssh` and `authorized_keys`. |
| `ssh_authorized_keys_manage_group` | `{{ ssh_authorized_keys_manage_user }}` | Group owner for `~/.ssh` and `authorized_keys`. |
| `ssh_authorized_keys_manage_home` | `/root` for `root`, otherwise `/home/<user>` | Target account home directory. Override when the account lives elsewhere. |
| `ssh_authorized_keys_manage_entries` | `[]` | Authorized key entries to render into the file. Must be non-empty when the role is enabled. |
| `ssh_authorized_keys_manage_exclusive` | `true` | `true` renders the complete file. `false` adds or updates only the listed entries and keeps every other line (see [Non-exclusive mode](#non-exclusive-mode)). |

## Authorized Key Entry Schema

Each item in `ssh_authorized_keys_manage_entries` supports:

| Field | Required | Description |
| --- | --- | --- |
| `key` | yes | Public key material. Usually `ssh-ed25519 AAAA...` or another OpenSSH public key line without key options. |
| `comment` | no | Optional trailing comment appended after `key`. |
| `key_options` | no | Optional OpenSSH `authorized_keys` options prepended before `key`. |

Notes:

- If your `key` value already includes a trailing comment, leave `comment` unset.
- In the default mode the role manages the complete file contents. Keys not present in `ssh_authorized_keys_manage_entries` are removed from the rendered file.
- In non-exclusive mode keys not present in `ssh_authorized_keys_manage_entries` are left alone.
- No field may contain a line break.

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

Add two keys for `root` and keep every key someone else installed:

```yaml
- name: Authorize operator keys alongside service keys
  hosts: all
  become: true
  roles:
    - role: local.ops_library.ssh_authorized_keys_manage
      vars:
        ssh_authorized_keys_manage_exclusive: false
        ssh_authorized_keys_manage_entries:
          - key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBASE64KEYFOROPS1"
            comment: "opsgate@runner"
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
