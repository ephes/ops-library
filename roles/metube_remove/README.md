# MeTube Remove Role

Removes the MeTube service and optional data.

Flags:

| Variable | Default | Description |
| --- | --- | --- |
| `metube_confirm_removal` | `false` | Must be `true` to proceed. |
| `metube_remove_install_dir` | `true` | Delete `{{ metube_install_dir }}` (sources + venv). |
| `metube_remove_state` | `true` | Delete `{{ metube_state_dir }}`. |
| `metube_remove_downloads` | `false` | Delete `{{ metube_download_dir }}` (dangerous, large). |
| `metube_remove_traefik_config` | `true` | Delete Traefik dynamic config. |
| `metube_remove_user` | `true` | Delete service user/group. |

Example:

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.metube_remove
      vars:
        metube_confirm_removal: true
        metube_remove_downloads: false
```
