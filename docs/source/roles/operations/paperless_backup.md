# Paperless Backup Role

Create comprehensive Paperless-ngx backups combining:

- `pg_dump` of the Paperless PostgreSQL database
- Rsync copies of media/data directories on `/mnt/cryptdata/paperless`
- Exporter artifacts via `document_exporter`
- Metadata (checksums, versions, size) plus optional controller download

## Usage

```yaml
- hosts: paperless
  roles:
    - role: local.ops_library.paperless_backup
      vars:
        paperless_backup_postgres_password: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['postgres_password'] }}"
        paperless_backup_prefix: manual
```

See `roles/paperless_backup/README.md` for disk-space checks, compression options, exporter flags, and troubleshooting tips.
