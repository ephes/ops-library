# vector_apt_install

Install the Vector apt repository and package on Debian/Ubuntu hosts.

This role is intentionally small. It owns only the shared apt/repository/package
bootstrap used by the Graphyard and Logyard Vector producer roles. It does not
manage `/etc/vector/config.d`, service environment, or any pipeline fragments.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `vector_apt_install_package_name` | `vector` | Package name to install |
| `vector_apt_install_repo_url` | `https://apt.vector.dev/` | Base apt repository URL |
| `vector_apt_install_repo_channel` | `stable` | Repository channel |
| `vector_apt_install_repo_version` | `vector-0` | Repository suite/component |
| `vector_apt_install_repo_key_url` | `https://keys.datadoghq.com/DATADOG_APT_KEY_CURRENT.public` | ASCII-armored repository key URL |
| `vector_apt_install_repo_key_tmp` | `/tmp/vector-datadog-archive-keyring.public` | Temporary download path for the key |
| `vector_apt_install_repo_keyring_path` | `/usr/share/keyrings/datadog-archive-keyring.gpg` | Installed dearmored keyring path |
| `vector_apt_install_repo_list_file` | `/etc/apt/sources.list.d/vector.list` | Apt source list path |
| `vector_apt_install_repo_legacy_deb822_files` | `[]` | Absolute consolidated `.sources` paths to migrate |

## Example

```yaml
- name: Install Vector prerequisites
  ansible.builtin.include_role:
    name: local.ops_library.vector_apt_install
  vars:
    vector_apt_install_package_name: vector
```

## Notes

- The role assumes `apt`-based hosts and declares tested Debian 12/13 support.
- Vector's `stable vector-0` repository is suite-independent; consumers must
  still verify the desired candidate for their release before an OS upgrade.
- Downstream roles are still responsible for validating Vector configuration and
  starting `vector.service`.

## Migrating a consolidated APT source

Set `vector_apt_install_repo_legacy_deb822_files` to the absolute `.sources`
paths containing old Vector entries. After configuring `vector.list`, the role
removes only an exact standalone stanza with the fields `Types: deb`, `URIs`,
`Suites`, `Components`, `Signed-By`, in that order, matching the current settings
(with the repository URL's trailing slash omitted). Other entries and layouts
remain untouched. Missing legacy files are skipped; changed files receive
Ansible timestamped backups ending in `~`. The separate managed source must
exist and match before cleanup runs. Repeated cleanup changes nothing.
With migration enabled, a full-role `--check` also requires the managed source
to exist already: check mode cannot create a replacement for cleanup to verify.

For an existing, correctly configured `vector.list`, `ansible.builtin.import_role`
with `tasks_from: repo_cleanup.yml` runs only this migration, without package
installation or a service restart. Do not list the managed source itself.
