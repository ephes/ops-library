# Webapp Deploy Internal Role

Internal helper role for the landed deploy helper extraction.

This role is not a public deployment entrypoint. It exists to hold the shared
deploy helpers extracted from the `fastdeploy_deploy`, `nyxmon_deploy`,
`archive_deploy`, `wagtail_deploy`, and `graphyard_ingress_deploy` roles while
keeping those public roles readable.

The safe extraction boundary currently stops at the systemd unit and Traefik
config steps. The remaining pilot-role task files still diverge materially in
user creation, source deployment, Python setup, and application
initialization, so they stay in the public roles. `graphyard_deploy` remains
outside the current helper boundary because it manages two systemd units and
has health checks but no `traefik.yml`.

That same boundary holds for the current adopters. `archive_deploy` and
`wagtail_deploy` fit the existing single-unit systemd and Traefik helpers,
while `graphyard_deploy` still stays outside the systemd helper because it
manages two distinct units. Its separate ingress role can still use
`traefik_config.yml`, which keeps the Traefik abstraction narrow without
inventing a multi-unit systemd helper.

Current helper task entrypoints:

- `systemd_service.yml`: render and enable a single application systemd unit
- `traefik_config.yml`: render a Traefik dynamic config and, when enabled,
  resolve its basic-auth hash through `traefik_basic_auth_hash.yml`
- `traefik_basic_auth_hash.yml`: resolve the bcrypt hash a Traefik basicAuth
  middleware renders for one user, for roles that render their Traefik file
  with their own template task

## Stable basic-auth hashes

bcrypt salts are random, so a role that hashes the password on every run
rewrites its Traefik dynamic file on every deploy, and a notified reload or
restart handler fires every time. `traefik_basic_auth_hash.yml` reads the
deployed file, takes the hash rendered as `"<user>:<hash>"` for the user and
reuses it when `htpasswd -v` confirms it still matches the current password
(checked against a private temporary file that holds only that entry; the
password goes to htpasswd on stdin). Only when the file, the entry or a match
is missing, or the hash is malformed, does it hash anew with `htpasswd -nBi`.
A password change therefore still rewrites the file once.

```yaml
- name: Resolve basic auth password hash
  ansible.builtin.include_role:
    name: local.ops_library.webapp_deploy_internal
    tasks_from: traefik_basic_auth_hash
  vars:
    webapp_deploy_internal_basic_auth_user: "{{ example_basic_auth_user }}"
    webapp_deploy_internal_basic_auth_password: "{{ example_basic_auth_password }}"
    webapp_deploy_internal_basic_auth_config_path: /etc/traefik/dynamic/example.yml
    webapp_deploy_internal_basic_auth_hash_var: example_basic_auth_password_hash
```

The target needs `htpasswd` (apache2-utils). The verification is read-only and
also runs in check mode; when a check-mode run finds no reusable hash it sets
a placeholder (`$2y$04$` followed by 53 `a`), so the template reports the
pending change without htpasswd having to be installed yet.

Every role that renders a basic-auth hash into Traefik uses it: the
`traefik_config.yml` callers (`fastdeploy_deploy`, `nyxmon_deploy`,
`chesslab_deploy`, `graphyard_ingress_deploy`, `work_app_deploy`) and
`echoport_deploy`, `homelab_deploy`, `jellyfin_deploy`, `metube_deploy`,
`minio_deploy`, `navidrome_deploy`, `ollama_proxy_deploy`, `open_webui_deploy`,
`open_webui_venv_deploy` and `weeknotes_home_deploy`. The Molecule scenario
`roles/webapp_deploy_internal/molecule/default` proves that a second run
changes nothing, that a password change replaces the hash and that a
malformed hash is replaced.

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
