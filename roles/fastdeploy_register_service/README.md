# FastDeploy Service Registration Role

Register a service runner with FastDeploy so the FastDeploy UI/API can trigger a narrowly scoped
`ops-control` deployment flow through a controlled `fastdeploy -> deploy -> root` privilege chain.

## What The Role Does

`fastdeploy_register_service` currently:

- creates the `deploy` user/group and its runner workspace under `/home/deploy/`
- optionally installs an age key at `/home/deploy/.config/sops/age/keys.txt`
- prepares `ops-control` for the runner:
  - `rsync`: syncs to `/home/deploy/ops-control`
  - `git`: clones or refreshes `/home/deploy/_workspace/ops-control`
- renders an owner-only runner to `/home/deploy/runners/<service>/deploy.py`
- optionally writes a deploy-user-only runner config payload to
  `/home/deploy/runners/<service>/deploy-config.json`
- copies that runner into `/home/fastdeploy/site/services/<service>/deploy.py` with owner-only
  permissions
- writes `/home/fastdeploy/site/services/<service>/config.json`
- installs `/etc/sudoers.d/fastdeploy_<service>`
- optionally calls `POST <fd_api_base>/services/sync`

The role does not generate `deploy.sh` or `playbook.yml`. Those belong to other FastDeploy
registration patterns such as `apt_upgrade_register`.

## Requirements

- FastDeploy must already be installed, including the `fastdeploy` user/group.
- Run the role with `become: true`.
- For the default `rsync` method, the controller must provide a readable local `ops-control`
  checkout via `fd_ops_control_local_path`.
- `rsync` must be available on the controller and target when using `fd_ops_control_method: rsync`.

## Default Paths

```text
/home/fastdeploy/site/services/<service>/
├── config.json
└── deploy.py

/home/deploy/
├── .config/sops/age/keys.txt
├── ops-control/
├── runners/<service>/deploy-config.json
├── runners/<service>/deploy.py
└── _workspace/

/etc/sudoers.d/fastdeploy_<service>
```

Security notes:

- `/home/deploy/runners/<service>/deploy.py` is written `0700` and owned by `deploy`.
- `/home/deploy/runners/<service>/deploy-config.json` is written `0600` and owned by `deploy` when
  `fd_runner_config` is provided.
- `/home/fastdeploy/site/services/<service>/deploy.py` is written `0700` and owned by `fastdeploy`.
- `/home/deploy/runners/<service>/` and `/home/deploy/.ssh/` are created `0700`.
- Prefer `fd_runner_config` for secret-bearing runner-time data. The default runner reads that
  private payload at execution time and writes any `ansible.extra_vars` values to a transient
  `0600` temp file instead of embedding them in the runner source or `ansible-playbook` argv.
- Prefer `ansible.extra_vars_from_sops` inside `fd_runner_config` when the runner can decrypt
  staged SOPS files at execution time. That keeps decrypted values out of long-lived runner config
  files while still feeding them to Ansible through the same transient temp file path.

## Key Variables

```yaml
service_name: nyxmon

fd_service_name: "{{ service_name | mandatory }}"
fd_service_description: "Deploy {{ fd_service_name }} via ops-control"

fd_fastdeploy_root: /home/fastdeploy/site
fd_fastdeploy_user: fastdeploy
fd_service_config_dir: "{{ fd_fastdeploy_root }}/services/{{ fd_service_name }}"

fd_deploy_user: deploy
fd_deploy_home: "/home/{{ fd_deploy_user }}"
fd_runner_script: "{{ fd_deploy_home }}/runners/{{ fd_service_name }}/deploy.py"
fd_runner_config_path: "{{ fd_deploy_home }}/runners/{{ fd_service_name }}/deploy-config.json"
fd_sudoers_file: "/etc/sudoers.d/fastdeploy_{{ fd_service_name }}"

fd_ops_control_method: rsync
fd_ops_control_local_path: /path/to/ops-control
fd_ops_control_remote_path: "{{ fd_deploy_home }}/ops-control"

fd_api_base: http://localhost:8000
fd_api_token: ""
fd_sync_services: true

fd_sops_age_key_contents: ""
fd_runner_content: ""
fd_runner_config: {}
```

Notes:

- `fd_service_name` defaults to `service_name` and is required.
- `fd_runner_content` overrides the default `deploy.py.j2` template.
- `fd_runner_config` writes a deploy-user-only JSON payload next to the runner. The default template
  merges that static payload with any runtime `DEPLOY_CONFIG_FILE`/`--config` data from FastDeploy.
- `fd_runner_config.ansible.extra_vars_from_sops` accepts a list of runtime secret sources. Each
  entry must define `path` plus a `vars` map of destination extra-var names to SOPS key paths. A
  mapping value can be either a string key path or an object with `path` and optional `default`.
- `fd_ops_control_local_path` is required when `fd_ops_control_method == "rsync"`.
- If `fd_api_token` is empty, the service sync call is skipped.

## Example

```yaml
- name: Register Nyxmon with FastDeploy
  hosts: fastdeploy_host
  become: true
  roles:
    - role: local.ops_library.fastdeploy_register_service
      vars:
        service_name: nyxmon
        fd_service_description: "Deploy nyxmon via ops-control"
        fd_ops_control_method: rsync
        fd_ops_control_local_path: "{{ playbook_dir }}/../ops-control"
        fd_sops_age_key_contents: "{{ lookup('file', lookup('env', 'HOME') ~ '/.config/sops/age/keys.txt') }}"
        fd_runner_config:
          ansible:
            extra_vars:
              release_channel: stable
            extra_vars_from_sops:
              - path: secrets/prod/nyxmon.yml
                vars:
                  nyxmon_secret_key: django_secret_key
          verify:
            systemd_service: nyxmon
        fd_api_token: "{{ fastdeploy_api_token }}"
```

## Execution Flow

1. FastDeploy starts `/home/fastdeploy/site/services/<service>/deploy.py`.
2. The sudoers rule allows that runner to execute as `deploy`.
3. The runner prepares `ops-control`:
   - `rsync`: uses the pre-synced checkout already placed at `/home/deploy/ops-control`
   - `git`: clones or refreshes a checkout in `/home/deploy/_workspace/ops-control`
4. The runner installs Ansible collections when `collections/requirements.yml` exists.
5. The runner merges the private `deploy-config.json` payload with any runtime FastDeploy config
   file, if present.
6. The runner resolves any `ansible.extra_vars_from_sops` entries at execution time using
   `sops -d --output-type json`, relative to the staged `ops-control` workspace unless absolute
   paths are provided.
7. The runner executes:

```text
ansible-playbook -i inventories/prod/hosts.yml playbooks/site.yml -l localhost --extra-vars filter=<service> --become --become-user root
```

8. Progress is emitted as NDJSON on stdout. If FastDeploy supplied callback URLs and a token, the
   runner also sends best-effort HTTP updates.

## Validation

Focused Molecule coverage for this role lives under:

```bash
just molecule-test fastdeploy_register_service
```
