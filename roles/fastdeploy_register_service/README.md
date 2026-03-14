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
├── runners/<service>/deploy.py
└── _workspace/

/etc/sudoers.d/fastdeploy_<service>
```

Security notes:

- `/home/deploy/runners/<service>/deploy.py` is written `0700` and owned by `deploy`.
- `/home/fastdeploy/site/services/<service>/deploy.py` is written `0700` and owned by `fastdeploy`.
- `/home/deploy/runners/<service>/` and `/home/deploy/.ssh/` are created `0700`.
- These tighter modes matter because custom runner content or rendered template defaults may embed
  deployment secrets or API credentials.

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
fd_sudoers_file: "/etc/sudoers.d/fastdeploy_{{ fd_service_name }}"

fd_ops_control_method: rsync
fd_ops_control_local_path: /path/to/ops-control
fd_ops_control_remote_path: "{{ fd_deploy_home }}/ops-control"

fd_api_base: http://localhost:8000
fd_api_token: ""
fd_sync_services: true

fd_sops_age_key_contents: ""
fd_runner_content: ""
```

Notes:

- `fd_service_name` defaults to `service_name` and is required.
- `fd_runner_content` overrides the default `deploy.py.j2` template.
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
        fd_api_token: "{{ fastdeploy_api_token }}"
```

## Execution Flow

1. FastDeploy starts `/home/fastdeploy/site/services/<service>/deploy.py`.
2. The sudoers rule allows that runner to execute as `deploy`.
3. The runner prepares `ops-control`:
   - `rsync`: uses the pre-synced checkout already placed at `/home/deploy/ops-control`
   - `git`: clones or refreshes a checkout in `/home/deploy/_workspace/ops-control`
4. The runner installs Ansible collections when `collections/requirements.yml` exists.
5. The runner executes:

```text
ansible-playbook -i inventories/prod/hosts.yml playbooks/site.yml -l localhost --extra-vars filter=<service> --become --become-user root
```

6. Progress is emitted as NDJSON on stdout. If FastDeploy supplied callback URLs and a token, the
   runner also sends best-effort HTTP updates.

## Validation

Focused Molecule coverage for this role lives under:

```bash
just molecule-test fastdeploy_register_service
```
