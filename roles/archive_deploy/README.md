# archive_deploy

Deploy the Archive Django service on a host with a local SQLite database, systemd, and Traefik.

This role covers the deployed Archive MVP through the current Milestone 6 slice:

- source deployment via `rsync` or `git`
- `uv`-managed virtualenv
- Django migrations and static collection
- admin/editor bootstrap user
- systemd web service plus enrichment worker
- public Traefik ingress
- automatic service restart when app source, environment, or dependency state changes

The enrichment worker performs Milestone 3 metadata extraction plus Milestone 4 short summary, long
summary, and tag generation, plus Milestone 5 transcript generation for audio/video items and the shipped
Milestone 6 media archival flow for direct remote audio, direct downloadable video files, and supported
YouTube page URLs. Summary generation uses an OpenAI-compatible API backend and retries failed summary jobs
with bounded backoff before leaving them in a failed state for operator review. Transcription defaults to
the same API key/base unless separate transcription settings are provided. Video-derived local audio still
requires `ffmpeg` on the worker host; the new YouTube page downloader is provided by the app's Python
dependencies and does not require a separate host binary. Because YouTube changes regularly, operators
should expect occasional `yt-dlp` dependency refreshes on redeploy. The media-archive worker timeout still
guards stalled work, but it is not a strict total runtime cap on a steady `yt-dlp` download.

Backup and restore are intentionally handled through Echoport orchestration, not `archive_backup` /
`archive_restore` roles. The primary backup target is the SQLite database at
`{{ archive_db_path }}` via the existing `echoport-backup` FastDeploy service.

## Contributor Notes

The deploy helper extraction keeps the public role entrypoint unchanged while
moving the duplicated single-unit systemd and Traefik rendering steps into the
internal helper role `local.ops_library.webapp_deploy_internal`. Archive still
owns its validation, source deployment, Django setup, templates, handlers, and
health verification flow.

## Variables

Required:

```yaml
archive_django_secret_key: "long-random-secret"
archive_api_token: "long-random-api-token"
archive_summary_api_key: "openai-or-compatible-api-key"
archive_admin_username: "archive"
archive_admin_password: "long-random-password"
archive_traefik_host: "archive.home.xn--wersdrfer-47a.de"
```

Common overrides:

```yaml
archive_source_path: "/Users/jochen/projects/archive"
archive_deploy_method: rsync
archive_django_allowed_hosts:
  - "127.0.0.1"
  - "archive.home.xn--wersdrfer-47a.de"
archive_django_csrf_trusted_origins:
  - "https://archive.home.xn--wersdrfer-47a.de"
archive_metadata_worker_interval: 10
archive_metadata_worker_limit: 10
archive_metadata_request_timeout: 15
archive_summary_request_timeout: 60
archive_transcription_request_timeout: 300
archive_summary_api_base: "https://api.openai.com/v1"
archive_summary_model: "gpt-4o-mini"
archive_transcription_api_base: "https://api.openai.com/v1"
archive_transcription_model: "gpt-4o-mini-transcribe"
```

## Example

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.archive_deploy
      vars:
        archive_source_path: "/Users/jochen/projects/archive"
        archive_django_secret_key: "{{ archive_secrets.django_secret_key }}"
        archive_api_token: "{{ archive_secrets.api_token }}"
        archive_summary_api_key: "{{ archive_secrets.summary_api_key }}"
        archive_summary_api_base: "{{ archive_secrets.summary_api_base }}"
        archive_summary_model: "{{ archive_secrets.summary_model }}"
        archive_transcription_api_key: "{{ archive_secrets.transcription_api_key | default(archive_secrets.summary_api_key) }}"
        archive_transcription_api_base: "{{ archive_secrets.transcription_api_base | default(archive_secrets.summary_api_base) }}"
        archive_transcription_model: "{{ archive_secrets.transcription_model | default('gpt-4o-mini-transcribe') }}"
        archive_admin_username: "{{ archive_secrets.admin_username }}"
        archive_admin_password: "{{ archive_secrets.admin_password }}"
        archive_traefik_host: "archive.home.xn--wersdrfer-47a.de"
        archive_django_allowed_hosts:
          - "127.0.0.1"
          - "archive.home.xn--wersdrfer-47a.de"
        archive_django_csrf_trusted_origins:
          - "https://archive.home.xn--wersdrfer-47a.de"
        archive_metadata_worker_interval: 10
```
