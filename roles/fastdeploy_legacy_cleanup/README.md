# fastdeploy_legacy_cleanup

Unregister retired FastDeploy services and remove legacy sudoers rules,
idempotently, so a redeploy converges to a host without them.

Written for the FastDeploy privilege reduction: the never-used
`fastdeploy-self` and `apt_upgrade_*` services carried the only rules that
made the `deploy` user root without restriction
(`deploy ALL=(root) NOPASSWD: ALL`, `deploy ALL=(postgres|fastdeploy) ALL`,
apt/ansible-playbook as root), and FastDeploy's wildcard rule
`fastdeploy ALL=(deploy) NOPASSWD: <services>/*/deploy.sh *` let fastdeploy run
any script it wrote into its own services directory.

## What the role does

1. Validates the lists (plain names; extra paths directly inside an allowed
   root).
2. Copies everything that still exists into one root-only tarball
   (`/var/backups/fastdeploy-legacy-cleanup/<UTC timestamp>.tar.gz`, `0600`;
   runner directories can hold deploy secrets), then removes:
   - `<services_path>/<name>` and `<runner_root>/<name>` for every service,
   - `/etc/sudoers.d/<file>` for every listed sudoers file,
   - every extra path.
3. Runs `visudo -c` on what is left.
4. When services were listed and the FastDeploy site exists, runs FastDeploy's
   own `commands.py syncservices` as the fastdeploy user: a service without a
   directory is deleted from the database together with its deployments. The
   play fails when FastDeploy kept a listed service (a running deployment).

Nothing is touched when nothing exists; the second run changes nothing.

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `fastdeploy_legacy_cleanup_services` | `[]` | FastDeploy service names to unregister. |
| `fastdeploy_legacy_cleanup_sudoers_files` | `[]` | Base names in `/etc/sudoers.d` to remove. |
| `fastdeploy_legacy_cleanup_extra_paths` | `[]` | More files/directories, each directly inside a root below. |
| `fastdeploy_legacy_cleanup_extra_path_roots` | `/home/deploy/runners`, `/home/fastdeploy/site/services` | Allowed parents for extra paths. |
| `fastdeploy_legacy_cleanup_services_path` | `/home/fastdeploy/site/services` | FastDeploy services directory. |
| `fastdeploy_legacy_cleanup_runner_root` | `/home/deploy/runners` | Runner directories. |
| `fastdeploy_legacy_cleanup_archive_dir` | `/var/backups/fastdeploy-legacy-cleanup` | Where the pre-removal tarball goes. |
| `fastdeploy_legacy_cleanup_sync_services` | `true` | Run the FastDeploy service sync after removing service directories. |
| `fastdeploy_legacy_cleanup_fastdeploy_user` | `fastdeploy` | User for the sync. |
| `fastdeploy_legacy_cleanup_site_path` | `/home/fastdeploy/site` | FastDeploy site (`commands.py`, `.env.shell`). |

## Example

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.fastdeploy_legacy_cleanup
      vars:
        fastdeploy_legacy_cleanup_services: [fastdeploy-self, apt_upgrade_local]
        fastdeploy_legacy_cleanup_sudoers_files:
          - fastdeploy
          - fastdeploy_fastdeploy-self
          - fastdeploy_self_deploy_users
          - apt_upgrade_apt_upgrade_local
        fastdeploy_legacy_cleanup_extra_paths:
          - /home/deploy/runners/fastdeploy-self-playbook.yml
```

## Undo

Archive members are stored relative to `/` (`etc/sudoers.d/<file>`,
`home/deploy/runners/<service>/...`). List with `tar -tzf <archive>` and put a
file back as root with `tar -xzf <archive> -C / <member>`, then rerun the
playbook that originally registered the service. Prefer not to: the removed rules were root grants.

## Testing

```bash
just molecule-test fastdeploy_legacy_cleanup
```
