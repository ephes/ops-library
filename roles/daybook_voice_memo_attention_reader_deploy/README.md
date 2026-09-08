# daybook_voice_memo_attention_reader_deploy

Provision one dedicated MinIO identity for the Daybook voice-memo attention
reader. The fixed `daybook-voice-memo-attention-read` policy permits exactly:

- `s3:ListBucket` on `obsidian`, only when `s3:prefix` equals `Inbox/Voice Memos/`.
- `s3:GetObject` on `obsidian/Inbox/Voice Memos/*`.

There are no write permissions, other prefixes, bucket-wide reads, admin actions,
or group memberships. The existing importer identity is independent.

## Requirements

Run as root on the MinIO server. The `mc` CLI must already have a working local
admin alias. Python 3 is required. Supply a freshly generated, dedicated access
key and secret from private encrypted inventory; never reuse another service's
identity or the MinIO root credentials.

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `daybook_voice_memo_attention_reader_access_key` | `CHANGEME` | New dedicated access key (letters, digits, hyphens, underscores), starting with a letter or digit, at least 16 characters |
| `daybook_voice_memo_attention_reader_secret_key` | `CHANGEME` | New dedicated secret, at least 32 characters; no newlines |
| `daybook_voice_memo_attention_reader_mc_bin` | `/usr/local/bin/mc` | Installed MinIO CLI |
| `daybook_voice_memo_attention_reader_alias` | `local` | Existing root-admin CLI alias |
| `daybook_voice_memo_attention_reader_python` | `/usr/bin/python3` | Server Python interpreter |
| `daybook_voice_memo_attention_reader_state_dir` | `/var/lib/daybook-voice-memo-attention-reader` | Root-only ownership marker and fixed policy |

Bucket, prefix, and policy name are deliberately fixed for this bounded pilot.
The role does not install reader credentials on Studio or activate Daybook.

## Example

```yaml
- name: Provision dedicated attention reader
  hosts: minio_servers
  become: true
  roles:
    - role: local.ops_library.daybook_voice_memo_attention_reader_deploy
      vars:
        daybook_voice_memo_attention_reader_access_key: "{{ attention_secrets.s3_access_key_id }}"
        daybook_voice_memo_attention_reader_secret_key: "{{ attention_secrets.s3_secret_access_key }}"
```

## Fail-closed ownership and recovery

The helper first reads the existing policy and identity, then refuses unexpected
inspection errors, broader/different policy documents, extra policy attachments,
groups, disabled users, or an existing identity without its root-only ownership
marker. It never replaces an existing policy or upserts an existing user's
secret. Existing correct installations are read-only and idempotent.

The marker contains SHA-256 fingerprints of the high-entropy credentials, not
the credentials. A changed key/secret, missing previously owned identity, or
interrupted creation requires explicit operator recovery. Inspect MinIO before
recovery; do not delete markers to force adoption. For credential rotation,
provision a fresh dedicated identity in a fresh state directory, verify its
restricted access, switch the reader's private credentials, then explicitly
remove the retired identity. Never broaden the fixed policy.

If provisioning fails after user creation but before marker persistence, it
leaves an orphan identity and refuses automatic adoption on rerun. Inspect and
remove that newly created orphan before retrying. The helper sends credentials
to `mc admin user add` on stdin, not process arguments. Ansible uses `no_log` for
the request and reports only a fixed success/failure category.

Check mode validates inputs and previews file installation but does not run the
provisioning helper or prove live permissions. A live deployment must verify an
exact-prefix list and object read succeed and write, another prefix, and a
bucket-wide list fail before activating the reader. Source discovery remains
read-only; source objects are never modified by this role.

## Validation

`uv run python -m unittest tests.test_daybook_voice_memo_attention_reader` covers
first creation, idempotency, missing-state refusal, policy/group drift, MinIO
inspection failures, input handling, and secret-free process arguments.
