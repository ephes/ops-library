# Webapp Deploy Internal Role

Internal helper role for the Wave 1 and Wave 2 deploy refactor waves.

This role is not a public deployment entrypoint. It exists to hold the shared
deploy helpers extracted from the `fastdeploy_deploy`, `nyxmon_deploy`,
`archive_deploy`, and `wagtail_deploy` roles while keeping those public roles
readable.

Current helper task entrypoints:

- `systemd_service.yml`: render and enable a single application systemd unit
- `traefik_config.yml`: render a Traefik dynamic config and, when enabled,
  generate a basic-auth hash

The Traefik helper defaults to the narrow no-auth case used by some callers.
Callers only need to pass the basic-auth variables and package settings when
their template actually consumes an auth hash.

Both helpers also tolerate omitted notify handler lists. That is only correct
for callers that intentionally do not want a handler notification from the
render step. Callers that expect a service restart, systemd reload, or Traefik
reload/restart must pass the appropriate `*_notify_handlers` list explicitly.

Intended usage:

```yaml
- name: Setup systemd service
  ansible.builtin.include_role:
    name: local.ops_library.webapp_deploy_internal
    tasks_from: systemd_service
  vars:
    webapp_deploy_internal_service_template_src: "templates/example.service.j2"
    webapp_deploy_internal_service_unit_dest: "/etc/systemd/system/example.service"
    webapp_deploy_internal_service_name: "example"
    webapp_deploy_internal_service_notify_handlers:
      - reload systemd
      - restart example
```

The helper resolves the caller role path from the include stack. Override
`webapp_deploy_internal_caller_role_path` only if a caller needs a different
template base path than its own role directory.

The caller remains responsible for:

- role-specific templates
- role-specific handlers
- role-specific validation and orchestration

This internal surface remains intentionally narrow. Additional deploy helpers
should only be added here when the duplication is proven by multiple roles and
the shared surface stays obvious.
