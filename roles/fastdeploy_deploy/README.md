# FastDeploy Deploy Role

This Ansible role deploys FastDeploy from a local source directory to a target server.

## Requirements

- Target server running Ubuntu/Debian
- PostgreSQL installed and running
- Local FastDeploy source code directory
- Ansible 2.9+
- ansible.posix collection (for synchronize module)
- community.general collection (for PostgreSQL modules)

## Role Variables

### Required Variables

These variables MUST be set when using this role:

```yaml
fastdeploy_source_path: /path/to/local/fastdeploy  # Local path to FastDeploy source
fastdeploy_secret_key: "generate-with-openssl-rand-hex-32"
fastdeploy_initial_password_hash: "bcrypt-hash-of-password"
fastdeploy_postgres_password: "secure-database-password"
```

### Important Configuration

```yaml
# API and frontend URLs
fastdeploy_api_url: "https://deploy.example.com"
fastdeploy_websocket_url: "wss://deploy.example.com/deployments/ws"

# Initial admin user
fastdeploy_initial_user: "admin"

# Traefik configuration
fastdeploy_traefik_host: "deploy.example.com"
```

### Optional Variables

See `defaults/main.yml` for all available variables and their default values.

## Dependencies

None.

## Example Playbook

### Minimal example (with secrets from SOPS):

```yaml
---
- hosts: production
  become: true
  vars:
    secrets: "{{ lookup('community.sops.sops', 'secrets/fastdeploy.yml') | from_yaml }}"
  roles:
    - role: ops_library.fastdeploy_deploy
      vars:
        fastdeploy_source_path: "/Users/john/projects/fastdeploy"
        fastdeploy_secret_key: "{{ secrets.secret_key }}"
        fastdeploy_initial_password_hash: "{{ secrets.password_hash }}"
        fastdeploy_postgres_password: "{{ secrets.db_password }}"
        fastdeploy_api_url: "https://deploy.mycompany.com"
        fastdeploy_websocket_url: "wss://deploy.mycompany.com/deployments/ws"
        fastdeploy_traefik_host: "deploy.mycompany.com"
```

### Full example with all options:

```yaml
---
- hosts: production
  become: true
  roles:
    - role: ops_library.fastdeploy_deploy
      vars:
        # Source and target
        fastdeploy_source_path: "/Users/john/projects/fastdeploy"
        fastdeploy_user: fastdeploy
        fastdeploy_home: /home/fastdeploy
        
        # Application settings
        fastdeploy_app_port: 9999
        fastdeploy_environment: production
        
        # Database
        fastdeploy_postgres_database: fastdeploy_prod
        fastdeploy_postgres_user: fastdeploy_app
        fastdeploy_postgres_password: "{{ vault_db_password }}"
        
        # Security
        fastdeploy_secret_key: "{{ vault_secret_key }}"
        fastdeploy_initial_user: admin
        fastdeploy_initial_password_hash: "{{ vault_admin_password_hash }}"
        
        # URLs
        fastdeploy_api_url: "https://deploy.mycompany.com"
        fastdeploy_websocket_url: "wss://deploy.mycompany.com/deployments/ws"
        
        # Features
        fastdeploy_build_frontend: true
        fastdeploy_create_initial_user: true
        fastdeploy_sync_services: true
        
        # Traefik
        fastdeploy_traefik_enabled: true
        fastdeploy_traefik_host: "deploy.mycompany.com"
        fastdeploy_traefik_cert_resolver: letsencrypt
```

## Deployment Process

1. Creates fastdeploy user and directory structure
2. Sets up PostgreSQL database and user
3. Syncs source code from local directory using rsync
4. Creates .env configuration file
5. Installs Python dependencies using uv
6. Builds frontend application
7. Creates initial admin user
8. Syncs services from filesystem
9. Sets up systemd service
10. Configures Traefik routing (optional)

## Security Notes

- Never commit secrets to version control
- Use Ansible Vault or SOPS for sensitive variables
- Generate strong passwords and secret keys
- The PostgreSQL password is stored in the .env file with 0600 permissions

## License

MIT

## Author Information

Created for the FastDeploy project.