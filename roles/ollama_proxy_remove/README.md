# ollama_proxy_remove

Remove the Traefik dynamic configuration for the Ollama proxy.

## Description

This role deletes the Traefik dynamic config file that exposes the Ollama API via HTTPS. It does not
remove Ollama itself.

## Requirements

- Linux target with Traefik installed
- Ansible 2.14+

## Role Variables

```yaml
ollama_proxy_remove_confirm: false
ollama_proxy_traefik_config_path: /etc/traefik/dynamic/ollama.yml
```

## Example Playbook

```yaml
- name: Remove Ollama proxy Traefik config
  hosts: macmini
  become: true
  vars:
    ollama_proxy_remove_confirm: true
  roles:
    - role: local.ops_library.ollama_proxy_remove
```

## Notes

- This role only removes the Traefik config file. The Ollama service and any models remain intact.
- Traefik is reloaded (or restarted if reload is unsupported) after removal.

## License

MIT
