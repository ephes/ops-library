# daybook_catalog_access_deploy

The MinIO identity the Daybook vault catalogue writes with, and its credentials
on the machine that runs the lane. The catalogue writes one note per item of the
owner's `matters`, `projects` and `writing` repositories under `Katalog/` in the
`obsidian` bucket, which every device's Obsidian syncs through `remotely-save`.
See Daybook's `docs/specs/2026-09-24-vault-catalogue.md`.

The fixed `daybook-catalog-writer` policy permits:

- `s3:ListBucket` on `obsidian`, only for the prefixes `Katalog/matters/`,
  `Katalog/projects/` and `Katalog/writing/`;
- `s3:GetObject` and `s3:PutObject` on `obsidian/Katalog/*`.

It grants no delete, nothing outside `Katalog/`, no administrative action and no
group membership. The catalogue's writes are conditional (`If-Match`,
`If-None-Match`), so it never overwrites a note someone else changed.

## Modes

`daybook_catalog_access_mode: server` runs as root on the MinIO host and
provisions the identity, fail closed and idempotent, with the same provisioner
as `daybook_work_source_access_deploy`: it creates a proven-absent identity
once, records credential fingerprints in a root-only marker, and refuses
adoption, changed credentials, a broader policy, extra attachments, group
membership, partial prior creation and ambiguous `mc` responses.

`daybook_catalog_access_mode: client` runs as the owner on the machine that runs
the lane (Atlas: user-owned, no root) and installs the owner-private (`0600`)
AWS credentials file with its own profile, plus the lane's private state and
session directories (`0700`).

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `daybook_catalog_access_mode` | `server` | `server` or `client` |
| `daybook_catalog_access_access_key` | `CHANGEME` | Dedicated access key, at least 16 safe characters |
| `daybook_catalog_access_secret_key` | `CHANGEME` | Dedicated secret, 32–256 characters without newlines |
| `daybook_catalog_access_mc_bin` | `/usr/local/bin/mc` | Server: installed MinIO CLI |
| `daybook_catalog_access_alias` | `local` | Server: existing root-admin CLI alias |
| `daybook_catalog_access_python` | `/usr/bin/python3` | Server: Python interpreter |
| `daybook_catalog_access_state_dir` | `/var/lib/daybook-catalog-access` | Server: root-only marker and fixed policy |
| `daybook_catalog_access_user` | the connecting user | Client: owner of the files |
| `daybook_catalog_access_root` | `~/Library/Application Support/Daybook/catalog` | Client: private root |
| `daybook_catalog_access_credentials_file` | `<root>/aws-credentials` | Client: credentials file |
| `daybook_catalog_access_profile` | `daybook-catalog` | Client: AWS profile name |

## Example

```yaml
- name: Provision the catalogue writer
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.daybook_catalog_access_deploy
      vars:
        daybook_catalog_access_mode: server
        daybook_catalog_access_access_key: "{{ catalog.aws_access_key_id }}"
        daybook_catalog_access_secret_key: "{{ catalog.aws_secret_access_key }}"

- name: Install the catalogue's credentials
  hosts: atlas
  roles:
    - role: local.ops_library.daybook_catalog_access_deploy
      vars:
        daybook_catalog_access_mode: client
        daybook_catalog_access_access_key: "{{ catalog.aws_access_key_id }}"
        daybook_catalog_access_secret_key: "{{ catalog.aws_secret_access_key }}"
```

The endpoint, region and bucket are not the role's: the scheduler profile's
`catalog.work.v1` kind carries them in its `run` block. The session the lane
starts runs as the owner and could read the credentials file; the policy is the
bound on what it can reach.
