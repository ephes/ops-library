# Takahe Shared Role

Provides shared defaults for the Takahe lifecycle roles (deploy, backup, restore, remove). This role is a helper and is typically pulled in automatically via role dependencies.

## Usage

```yaml
- hosts: takahe
  become: true
  roles:
    - role: local.ops_library.takahe_shared
```

## Notes

- Most operators do **not** call this role directly; it exists so other roles share a single default variable set.
- See `defaults/main.yml` for the complete variable reference.
- `takahe_traefik_legacy_config_paths` defaults to `[]`. The deploy role uses it
  to retire explicitly listed obsolete YAML files after rendering its managed
  route; see the [migration procedure](../takahe_deploy/README.md#migrating-legacy-traefik-routes).

## License

MIT
