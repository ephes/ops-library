# MinIO Shared Helper

Internal helper task library for MinIO roles.

## Current role surface

`minio_shared` is intentionally not a shared-defaults role. It currently exists
to expose the helper task file `tasks/mc_host_env.yml`, which builds consistent
`MC_HOST_*` environment facts for MinIO-related tasks.

Current callers in this repo:

- `minio_backup`
- `minio_restore`

## Usage

Callers include the task file directly:

```yaml
- name: Build mc helper facts
  ansible.builtin.include_tasks:
    file: "{{ role_path }}/../minio_shared/tasks/mc_host_env.yml"
  vars:
    mc_helper_register_var: minio_restore_mc_helper
```

## Notes

- There is no `defaults/main.yml` shared-defaults surface here.
- Treat this as an internal implementation detail, not as a public lifecycle
  entrypoint.

## License

MIT
