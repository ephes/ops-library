# Restore Pilot Internal Role

Internal helper role for the Wave 4 restore pilot extraction.

This role is not a public restore entrypoint. It exists to hold the narrow,
repo-proven scaffold shared by `fastdeploy_restore` and `unifi_restore` while
keeping those public roles readable and behaviorally stable.

Current helper task entrypoints:

- `scaffold.yml`: run the pilot `block`/`rescue`/`always` orchestration around
  caller-owned `validate`, `prepare`, `restore`, `verify`, `rollback`, and
  `cleanup` task files
- `host_local_validate.yml`: resolve a host-local restore artifact, extract it
  into a staging directory when needed, load `metadata.yml`, and optionally
  validate `manifest.sha256`
  When `latest` archive exclusions are configured, they are soft preferences:
  if every discovered archive matches the exclusion regex, the helper falls
  back to the unfiltered archive list instead of failing outright.

The caller remains responsible for:

- role-specific safety backup creation
- role-specific restore and rollback logic
- metadata-derived facts that depend on the service schema
- service-specific health verification and cleanup

Intended usage:

```yaml
- name: Run pilot scaffold
  ansible.builtin.include_role:
    name: local.ops_library.restore_pilot_internal
    tasks_from: scaffold
  vars:
    restore_pilot_internal_timestamp_var: example_restore_timestamp
    restore_pilot_internal_operation_successful_var: example_restore_operation_successful
    restore_pilot_internal_validate_tasks_file: validate.yml
    restore_pilot_internal_restore_tasks_file: restore.yml
    restore_pilot_internal_verify_tasks_file: verify.yml
    restore_pilot_internal_rollback_tasks_file: rollback.yml
    restore_pilot_internal_cleanup_tasks_file: cleanup.yml
```

```yaml
- name: Resolve host-local restore artifact
  ansible.builtin.include_role:
    name: local.ops_library.restore_pilot_internal
    tasks_from: host_local_validate
  vars:
    restore_pilot_internal_role_label: Example
    restore_pilot_internal_archive: "{{ example_restore_archive }}"
    restore_pilot_internal_archive_search_root: "{{ example_restore_archive_search_root }}"
    restore_pilot_internal_stage_dir: "{{ example_restore_stage_dir }}"
    restore_pilot_internal_validate_checksums: true
    restore_pilot_internal_resolved_artifact_path_var: example_restore_archive_path
    restore_pilot_internal_snapshot_dir_var: example_restore_snapshot_dir
    restore_pilot_internal_metadata_var: example_restore_metadata
```

This helper remains intentionally narrow. It is not a generic restore framework
for delayed roles. Additional shared restore logic should only move here when
multiple restore roles prove the same boundary in code and tests.
