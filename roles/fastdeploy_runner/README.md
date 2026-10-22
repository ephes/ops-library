# fastdeploy_runner

Install a script that FastDeploy starts through sudo where the `fastdeploy`
user cannot change it, and register it with FastDeploy.

FastDeploy runs a service as `sudo -u deploy <deploy_script> --config <file>`;
backup runners that need root re-run themselves with `sudo -n <script>`
through a second rule (`deploy ALL=(root)`). Whoever can change such a script,
or rename a directory above it, runs code as root. The `fastdeploy` user owns
FastDeploy's site directory (`/home/fastdeploy/site`), so nothing below it may
be named in sudoers, including the services root.

The role:

- creates `/usr/local/libexec/fastdeploy/<service>/` (root:root `0755`,
  directly below the libexec root, also root:root `0755`) and checks that
  every directory above the libexec root is root-owned and writable only by
  root;
- renders the script there from `fastdeploy_runner_template` (or writes
  `fastdeploy_runner_content`) as root:`deploy` `0750`: the deploy user can
  read and run it, fastdeploy can neither read nor change it;
- makes the services root and `<services root>/<service>/` root-owned and
  writes `config.json` (root `0644`) whose `deploy_script` is the absolute
  script path (FastDeploy runs absolute paths as they are);
- writes the sudoers file with fixed paths only:
  `fastdeploy ALL=(deploy) NOPASSWD:NOSETENV: <script> *` and, with
  `fastdeploy_runner_run_as`, `deploy ALL=(<run_as>) NOPASSWD:NOSETENV: <script> *`;
- runs FastDeploy's `commands.py syncservices` as the fastdeploy user (never
  as root: the virtualenv belongs to fastdeploy), so the stored service points
  at the new path;
- then removes the old copies (`fastdeploy_runner_legacy_files`, by default
  `<services root>/<service>/backup.py`).

Re-running it changes nothing (Molecule checks idempotence). Between writing
the sudoers file and the sync (a second or two) a run started with the old
path is refused; register outside the backup schedule.

## Variables

| Variable | Default | Description |
|---|---|---|
| `fastdeploy_runner_service` | (required) | FastDeploy service name, e.g. `delve-backup` |
| `fastdeploy_runner_description` | service name | Shown in FastDeploy |
| `fastdeploy_runner_steps` | (required) | Step names, in order |
| `fastdeploy_runner_template` / `fastdeploy_runner_content` | `""` | Script source; exactly one |
| `fastdeploy_runner_script_name` | `backup.py` | File name of the script |
| `fastdeploy_runner_libexec_root` | `/usr/local/libexec/fastdeploy` | Root-owned parent of the per-service directories |
| `fastdeploy_runner_dir` | `<libexec root>/<service>` | Must sit directly below the libexec root |
| `fastdeploy_runner_script_group` / `fastdeploy_runner_script_mode` | deploy user / `0750` | `0755` is accepted too |
| `fastdeploy_runner_fastdeploy_root` | `/home/fastdeploy/site` | FastDeploy site |
| `fastdeploy_runner_services_root` | `<site>/services` | |
| `fastdeploy_runner_config_dir` | `<services root>/<service>` | Holds only `config.json` |
| `fastdeploy_runner_fastdeploy_user` / `fastdeploy_runner_deploy_user` | `fastdeploy` / `deploy` | |
| `fastdeploy_runner_run_as` | `""` | `root` adds the `deploy -> root` rule |
| `fastdeploy_runner_sudoers_file` | `/etc/sudoers.d/<service with _>` | Keep the existing file name when migrating |
| `fastdeploy_runner_legacy_files` | `[<config dir>/backup.py]` | Removed after the sync |
| `fastdeploy_runner_sync` | `true` | Run `commands.py syncservices` as fastdeploy. With `false` the caller must sync before the next run: FastDeploy keeps the old path until then, and sudo refuses it |

## Example

```yaml
- name: Install the delve backup runner
  ansible.builtin.include_role:
    name: local.ops_library.fastdeploy_runner
  vars:
    fastdeploy_runner_service: delve-backup
    fastdeploy_runner_description: "Delve backend backup"
    fastdeploy_runner_steps: [init, backup_db, upload, verify, result]
    fastdeploy_runner_template: "{{ playbook_dir }}/../../ops-library/roles/echoport_backup/templates/delve_backup.py.j2"
    fastdeploy_runner_run_as: root
    fastdeploy_runner_sudoers_file: /etc/sudoers.d/delve_backup
```

The template is rendered with the play's variables, as before.

## Backups of FastDeploy

FastDeploy's own backups (`fastdeploy_backup`, Echoport `fastdeploy-backup`)
archive `config.json` and the sudoers files, not the runner directory, and
restores never write it: code that sudo runs as root is rendered from its
template by the registration, not taken from an archive. A restore on the
same host keeps the runners; on a new host, rerun the registrations.

## What stays possible

FastDeploy (and anyone with a FastDeploy service token for the service) can
still start the script with any `--config` context, including a restore.
Restricting that is a separate step (token issuance and per-target
allowlists).

## Testing

```bash
just molecule-test fastdeploy_runner
```

The scenario starts from the old layout (fastdeploy-owned services root and
script, sudoers naming it), checks that fastdeploy and deploy can neither
change nor rename the script or its directories, that the old path is
refused, that the sync ran as fastdeploy, that a second run changes nothing,
and that the runner still reaches root through
`sudo -u deploy <script> --config <file>` and its own `sudo -n`.
