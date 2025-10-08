# Role Catalog

Complete reference for all roles in the ops-library collection.

```{toctree}
:maxdepth: 1
:caption: Role Categories

deployment/index
removal/index
registration/index
bootstrap/index
testing/index
```

## Role Categories

### Deployment Roles

Deploy and configure services for your homelab infrastructure.

- {doc}`deployment/fastdeploy_deploy` - FastDeploy web deployment platform
- {doc}`deployment/nyxmon_deploy` - Nyxmon monitoring service
- {doc}`deployment/traefik_deploy` - Traefik reverse proxy
- {doc}`deployment/dns_deploy` - DNS service deployment
- {doc}`deployment/homelab_deploy` - Homelab infrastructure
- {doc}`deployment/fastdeploy_self_deploy` - FastDeploy self-deployment

### Removal Roles

Safely remove services and clean up resources.

- {doc}`removal/fastdeploy_remove` - Remove FastDeploy
- {doc}`removal/nyxmon_remove` - Remove Nyxmon
- {doc}`removal/traefik_remove` - Remove Traefik
- {doc}`removal/dns_remove` - Remove DNS service

### Registration Roles

Register services with FastDeploy for remote execution.

- {doc}`registration/apt_upgrade_register` - Register apt upgrade tasks
- {doc}`registration/fastdeploy_register_service` - Generic service registration

### Bootstrap Roles

Install required tools and dependencies.

- {doc}`bootstrap/ansible_install` - Install Ansible on controller
- {doc}`bootstrap/uv_install` - Install uv for Python
- {doc}`bootstrap/sops_dependencies` - Install age/SOPS

### Testing Roles

Development and testing utilities.

- {doc}`testing/test_dummy` - Demonstration service for testing

## Legacy Roles

These roles remain available for backward compatibility:

- `python_app_systemd` - Generic Python app systemd service
- `python_app_django` - Django application deployment

See individual role documentation for complete details on variables, requirements, and usage examples.
