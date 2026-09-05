from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles/echoport_deploy"
SCHEDULER_PATH = ROLE / "tasks/scheduler.yml"
ENV_TEMPLATE_PATH = ROLE / "templates/echoport.env.j2"
DEFAULTS_PATH = ROLE / "defaults/main.yml"


def _tasks() -> list[dict]:
    return yaml.safe_load(SCHEDULER_PATH.read_text(encoding="utf-8"))


def _task(name: str) -> dict:
    return next(task for task in _tasks() if task["name"] == name)


def test_cleanup_user_gets_a_verified_mc_alias_before_the_cron_exists() -> None:
    names = [task["name"] for task in _tasks()]
    alias_set = names.index("scheduler | Configure mc alias for cleanup user")
    verify = names.index("scheduler | Verify cleanup user can reach the MinIO bucket")
    cron = names.index("scheduler | Setup cleanup cron job")
    assert alias_set < verify < cron

    cron_task = _task("scheduler | Setup cleanup cron job")
    alias_task = _task("scheduler | Configure mc alias for cleanup user")
    verify_task = _task("scheduler | Verify cleanup user can reach the MinIO bucket")
    # The cron runs as the service user, so the alias must be created as that
    # user too, not as root like the upload scripts.
    assert cron_task["ansible.builtin.cron"]["user"] == "{{ echoport_user }}"
    assert alias_task["become_user"] == "{{ echoport_user }}"
    assert verify_task["become_user"] == "{{ echoport_user }}"
    assert alias_task["no_log"] is True
    assert verify_task["changed_when"] is False


def test_alias_is_only_rewritten_when_url_or_credentials_differ() -> None:
    alias_task = _task("scheduler | Configure mc alias for cleanup user")
    conditions = " ".join(alias_task["when"])
    assert "URL | default('') != echoport_minio_url" in conditions
    assert "accessKey | default('') != echoport_minio_access_key" in conditions
    assert "secretKey | default('') != echoport_minio_secret_key" in conditions


def test_cleanup_requires_minio_credentials() -> None:
    require = _task("scheduler | Require MinIO access for retention cleanup")
    assert require["when"] == "echoport_cleanup_enabled"
    assert "echoport_minio_url | length > 0" in require["ansible.builtin.assert"]["that"]
    assert 'echoport_minio_secret_key != "CHANGEME"' in require["ansible.builtin.assert"]["that"]

    defaults = yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8"))
    assert defaults["echoport_minio_alias"] == "minio"
    assert defaults["echoport_minio_url"] == ""
    assert defaults["echoport_minio_secret_key"] == ""


def test_env_file_points_the_app_at_the_service_user_alias() -> None:
    template = Environment(autoescape=False).from_string(
        ENV_TEMPLATE_PATH.read_text(encoding="utf-8")
    )
    rendered = template.render(
        echoport_django_settings_module="config.settings.production",
        echoport_django_allowed_hosts="127.0.0.1",
        echoport_django_debug=False,
        echoport_fastdeploy_base_url="http://localhost:8000",
        echoport_app_host="127.0.0.1",
        echoport_app_port=8100,
        echoport_cache_dir="/home/echoport/site/cache",
        echoport_allowed_path_prefixes=["/home/"],
        echoport_user="echoport",
        echoport_minio_mc_path="/usr/local/bin/mc",
        echoport_minio_alias="minio",
    )
    assert "MINIO_MC_PATH=/usr/local/bin/mc" in rendered
    assert "MINIO_ALIAS=minio" in rendered
