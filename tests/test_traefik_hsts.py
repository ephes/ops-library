"""No implicit HSTS preload; two mail UIs may preserve explicit existing policy."""

import unittest
from pathlib import Path

import jinja2
import yaml
from ansible.plugins.filter.core import to_bool

ROLES = Path(__file__).resolve().parents[1] / "roles"


class TraefikHstsTest(unittest.TestCase):
    def test_no_role_template_enables_preload(self):
        templates = sorted(ROLES.glob("*/templates/**/*.j2"))
        self.assertTrue(templates)
        for template in templates:
            with self.subTest(template=str(template.relative_to(ROLES))):
                relative = str(template.relative_to(ROLES))
                mail_routes = {
                    "postfixadmin_deploy/templates/traefik-postfixadmin.yml.j2",
                    "snappymail_deploy/templates/traefik-snappymail.yml.j2",
                }
                if relative not in mail_routes:
                    self.assertNotIn("stsPreload", template.read_text())
                    continue
                app = relative.split("_deploy/")[0]
                defaults = yaml.safe_load((ROLES / (app + "_shared") / "defaults/main.yml").read_text())
                key = app + "_traefik_sts_preload"
                self.assertIs(defaults[key], False)
                env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True)
                env.filters["bool"] = to_bool
                source = env.from_string(template.read_text())
                self.assertNotIn("stsPreload", source.render(defaults))
                for value in (True, "true"):
                    self.assertEqual(source.render({**defaults, key: value}).count("stsPreload: true"), 1)
                self.assertNotIn("stsPreload", source.render({**defaults, key: "false"}))


if __name__ == "__main__":
    unittest.main()
