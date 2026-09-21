# software_estate_remove

Removes `/usr/local/lib/software-estate`, including its optional bundled Syft
scanner. No applications, existing software-live collectors or caller-owned reports
are removed. This role currently has no scheduler to disable.

`software_estate_remove_install_dir` defaults to and must equal that dedicated path.

```yaml
- name: Remove optional software estate tools
  hosts: application_servers
  become: true
  roles:
    - role: local.ops_library.software_estate_remove
```
