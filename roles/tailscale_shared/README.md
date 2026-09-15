# Tailscale Shared Role

Shared defaults for the Tailscale lifecycle roles.

## Current role surface

This role provides the shared variable surface used by:

- `tailscale_deploy`
- `tailscale_backup`
- `tailscale_restore`
- `tailscale_remove`

## Usage

This role is usually loaded automatically through sibling lifecycle-role
dependencies:

```yaml
- hosts: edge
  become: true
  roles:
    - role: local.ops_library.tailscale_deploy
```

## Notes

- Most operators do not call this role directly.
- `tailscale_repo_sources_file` and the legacy-cleanup
  `tailscale_repo_list_file` default to paths derived from
  `tailscale_repo_name`; override a path only when intentionally using a custom
  repository filename.
- See `defaults/main.yml` for the full variable reference.

## License

MIT
