# test_dummy Role

A sample role used for development and testing of FastDeploy integrations.

## Purpose
- Demonstrates how a service can expose JSON status updates during deployment.
- Provides a lightweight workload for exercising registration and deployment flows end-to-end.

## Usage
```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.test_dummy
```

## Notes
- Intended for lab/testing environments only; it does not install a real service.
- Useful when validating FastDeploy registration (`fastdeploy_register_service`) without touching production services.
