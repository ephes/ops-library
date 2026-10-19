"""Role templates must not opt domains into browser HSTS preload."""

import unittest
from pathlib import Path

ROLES = Path(__file__).resolve().parents[1] / "roles"


class TraefikHstsTest(unittest.TestCase):
    def test_no_role_template_enables_preload(self):
        templates = sorted(ROLES.glob("*/templates/**/*.j2"))
        self.assertTrue(templates)
        for template in templates:
            with self.subTest(template=str(template.relative_to(ROLES))):
                # Omit the setting entirely, including variable-driven opt-ins.
                self.assertNotIn("stsPreload", template.read_text())


if __name__ == "__main__":
    unittest.main()
