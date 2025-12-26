# Mastodon Shared Role

Provides shared defaults for the Mastodon lifecycle roles (deploy, backup, restore, remove). This role is a helper and is typically pulled in automatically via role dependencies.

## Usage

```yaml
- hosts: mastodon
  become: true
  roles:
    - role: local.ops_library.mastodon_shared
```

## Notes

- Most operators do **not** call this role directly; it exists so other roles share a single default variable set.
- See `defaults/main.yml` for the complete variable reference.

## License

MIT
