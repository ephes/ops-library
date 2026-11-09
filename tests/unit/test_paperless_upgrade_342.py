"""Keep the Ansible rollback release aligned with the typed deployment."""

from pathlib import Path

import yaml


ROLE = Path(__file__).resolve().parents[2] / "roles/paperless_deploy"


def test_release_and_thumbnail_dependencies():
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert defaults["paperless_version"] == "3.4.2"
    assert defaults["paperless_release_checksums"]["3.4.2"] == (
        "sha256:599be82cd8fc184436b757f9b193101fb71a90bf0facf5695dcda43152fffc85"
    )
    assert "poppler-utils" in defaults["paperless_system_packages"]
    assert "imagemagick" not in defaults["paperless_system_packages"]


def test_managed_environment_drops_removed_upstream_settings() -> None:
    template = (ROLE / "templates/paperless.env.j2").read_text()
    for removed in (
        "PAPERLESS_CONVERT_BINARY",
        "PAPERLESS_CONVERT_MEMORY_LIMIT",
        "PAPERLESS_CONVERT_TMPDIR",
        "PAPERLESS_GS_BINARY",
        "MAGICK_TMPDIR",
    ):
        assert removed not in template
