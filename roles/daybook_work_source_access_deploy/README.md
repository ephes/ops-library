# daybook_work_source_access_deploy

Provision a reusable, read-only MinIO identity for Daybook working context. The
fixed `daybook-work-source-read` policy permits `s3:ListBucket` on the `obsidian`
bucket and `s3:GetObject` for every object in that bucket. It grants no writes,
deletes, administrative actions, or group membership.

This identity is independent of the Voice Memos importer, Daybook session
lifecycle credentials, and the retired attention reader.

## Requirements

Run as root on the MinIO server. The `mc` CLI must already have a working
root-admin alias. Python 3 is required. Pass newly generated credentials from
private encrypted inventory.

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `daybook_work_source_access_access_key` | `CHANGEME` | Dedicated access key, at least 16 safe characters |
| `daybook_work_source_access_secret_key` | `CHANGEME` | Dedicated secret, 32–256 characters without newlines |
| `daybook_work_source_access_mc_bin` | `/usr/local/bin/mc` | Installed MinIO CLI |
| `daybook_work_source_access_alias` | `local` | Existing root-admin CLI alias |
| `daybook_work_source_access_python` | `/usr/bin/python3` | Server Python interpreter |
| `daybook_work_source_access_state_dir` | `/var/lib/daybook-work-source-access` | Root-only ownership marker and fixed policy |

## Example

```yaml
- name: Provision Daybook work source access
  hosts: minio_servers
  become: true
  roles:
    - role: local.ops_library.daybook_work_source_access_deploy
      vars:
        daybook_work_source_access_access_key: "{{ work_source.aws_access_key_id }}"
        daybook_work_source_access_secret_key: "{{ work_source.aws_secret_access_key }}"
```

The role verifies the exact policy, identity status, attachment, and absence of
group memberships. A root-only marker contains credential fingerprints. It
creates a proven-absent identity once and refuses adoption, changed credentials,
broader policies, partial prior creation, and ambiguous `mc` responses.

The helper sends credentials to `mc admin user add` through stdin and Ansible
suppresses secret-bearing task output. The role provisions server-side access;
the consumer role is responsible for installing an owner-private AWS shared
credentials file.
