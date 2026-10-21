# MeTube Shared Role

Shared defaults for the MeTube lifecycle roles.

## Current role surface

This role provides the shared variable surface used by:

- `metube_deploy`
- `metube_backup`
- `metube_restore`
- `metube_remove`

## Usage

This role is usually loaded automatically through sibling lifecycle-role
dependencies:

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.metube_deploy
```

## Notes

- Most operators do not call this role directly.
- See `defaults/main.yml` for the full variable reference.

## License

MIT

## Verified uv bootstrap

`metube_uv_version` defaults to `0.13.4`, matching the verified release
checksums in `uv_install`. When overriding this version, also supply matching
`uv_checksum` entries for each target (see the `uv_install` role README).
Bump the version and checksum together; `latest` is no longer accepted.
