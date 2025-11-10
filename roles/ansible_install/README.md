# Ansible Install Role

Installs Ansible and required collections on a controller host.

## Features
- Installs the desired Ansible version via the system package manager or pip (configurable).
- Ensures helper tools such as `ansible-galaxy` are available.
- Optionally installs common collections used across the homelab (`community.general`, `ansible.posix`).

## Variables
See `defaults/main.yml` for the list of supported toggles (`ansible_install_method`, `ansible_install_packages`, etc.).

## Example
```yaml
- hosts: controller
  become: true
  roles:
    - role: local.ops_library.ansible_install
      vars:
        ansible_install_method: pip
```

## Notes
- Designed for controller bootstrap tasks; normally run once when preparing a development workstation or CI runner.
