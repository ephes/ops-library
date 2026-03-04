# graphyard_auth_bootstrap_deploy

Idempotently bootstrap Graphyard app and Grafana login credentials on an existing Graphyard stack.

## What This Role Manages

- Ensures a Django user exists with expected privileges (`is_active`, `is_staff`, `is_superuser`) and password.
- Verifies Grafana admin password by comparing the desired secret against Grafana's stored password hash in SQLite.
- Resets Grafana admin password only when the desired password hash does not match.

This role is intended to run **after** Graphyard and Grafana are already running on the host.

## Important Defaults

```yaml
graphyard_auth_bootstrap_enabled: false

graphyard_auth_bootstrap_system_user: "graphyard"
graphyard_auth_bootstrap_python: "/opt/apps/graphyard/site/.venv/bin/python"
graphyard_auth_bootstrap_manage_py: "/opt/apps/graphyard/site/src/django/manage.py"
graphyard_auth_bootstrap_workdir: "/opt/apps/graphyard/site/src/django"

graphyard_auth_bootstrap_django_username: "CHANGEME"
graphyard_auth_bootstrap_django_password: "CHANGEME"

graphyard_auth_bootstrap_grafana_container_name: "graphyard-grafana"
graphyard_auth_bootstrap_grafana_admin_user: "admin"
graphyard_auth_bootstrap_grafana_admin_password: "CHANGEME"
graphyard_auth_bootstrap_grafana_cli_bin: "/usr/share/grafana/bin/grafana"
graphyard_auth_bootstrap_grafana_homepath: "/usr/share/grafana"
graphyard_auth_bootstrap_grafana_db_path: "/var/lib/graphyard/grafana/grafana.db"
```

## Example

```yaml
- name: Bootstrap Graphyard app + Grafana credentials
  hosts: macmini
  become: true
  vars:
    graphyard_secrets: "{{ lookup('community.sops.sops', playbook_dir + '/../secrets/prod/graphyard.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.graphyard_auth_bootstrap_deploy
      vars:
        graphyard_auth_bootstrap_enabled: true
        graphyard_auth_bootstrap_django_username: "{{ graphyard_secrets.django_bootstrap_username }}"
        graphyard_auth_bootstrap_django_password: "{{ graphyard_secrets.django_bootstrap_password }}"
        graphyard_auth_bootstrap_grafana_admin_password: "{{ graphyard_secrets.grafana_admin_password }}"
```

## Notes

- Keep credential values in SOPS-managed secrets (`ops-control/secrets/prod/graphyard.yml`).
- This role uses `no_log: true` for all tasks that handle credential values.
- The role clears Grafana login-attempt lockout rows for the admin user on each run.
