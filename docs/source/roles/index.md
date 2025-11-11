# Role Catalog

Complete reference for all roles in the ops-library collection.

```{toctree}
:maxdepth: 1
:caption: Role Categories

deployment/index
removal/index
operations/index
registration/index
bootstrap/index
testing/index
```

## Role Categories

### Deployment Roles

Deploy and configure services for your homelab infrastructure. See the {doc}`deployment role index <deployment/index>` for all roles (FastDeploy, Nyxmon, Traefik, DNS, Homelab, Home Assistant, Paperless, etc.).

### Removal Roles

Safely remove services and clean up resources. Refer to the {doc}`removal role index <removal/index>` for FastDeploy, Nyxmon, Traefik, DNS, Home Assistant, Paperless, and friends.

### Operations Roles

Disaster-recovery workflows for long-lived services. See the {doc}`operations role index <operations/index>` for Home Assistant and Paperless backup/restore tooling.

### Registration Roles

Register services with FastDeploy for remote execution. Details live in the {doc}`registration role index <registration/index>`.

### Bootstrap Roles

Install required tools and dependencies. Consult the {doc}`bootstrap role index <bootstrap/index>` for Ansible, uv, SOPS, PostgreSQL, Redis, etc.

### Testing Roles

Development and testing utilities live in the {doc}`testing role index <testing/index>`.

## Removed in v2.0.0

The following legacy roles were removed in version 2.0.0:

- `python_app_systemd` - Use dedicated `*_deploy` roles instead (e.g., `fastdeploy_deploy`, `nyxmon_deploy`)
- `python_app_django` - Use dedicated `*_deploy` roles instead

**Migration:** Follow the dedicated role pattern for your services. See existing deployment roles for examples.

See individual role documentation for complete details on variables, requirements, and usage examples.
