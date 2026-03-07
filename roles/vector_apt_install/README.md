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

## Example

```yaml
- name: Install Vector prerequisites
  ansible.builtin.include_role:
    name: local.ops_library.vector_apt_install
  vars:
    vector_apt_install_package_name: vector
```

## Notes

- The role assumes `apt`-based hosts.
- Downstream roles are still responsible for validating Vector configuration and
  starting `vector.service`.
