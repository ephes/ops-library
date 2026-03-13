# Homelab Shared Role

Shared defaults and shared facts for the Homelab lifecycle roles.

## Current role surface

- Shared defaults for `homelab_deploy`, `homelab_backup`, `homelab_restore`, and `homelab_remove`
- Exports the `homelab_paths` fact from `tasks/main.yml` so sibling roles can reuse the same path map

## Usage

This role is normally loaded automatically through sibling lifecycle-role
dependencies:

```yaml
- hosts: homelab
  become: true
  roles:
    - role: local.ops_library.homelab_deploy
```

Most operators do not call `local.ops_library.homelab_shared` directly.

## Notes

- Shared variables live in `defaults/main.yml`.
- Shared facts live in `tasks/main.yml`.

## License

MIT
