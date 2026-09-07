"""Parse Jinja templates without rendering variables or evaluating filters."""

import sys
from pathlib import Path

from jinja2 import Environment, TemplateSyntaxError


def main(paths: list[str]) -> int:
    environment = Environment(extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"])
    failed = False
    for filename in paths:
        try:
            environment.parse(Path(filename).read_text(encoding="utf-8"), name=filename)
        except (OSError, UnicodeError, TemplateSyntaxError) as error:
            print(f"{filename}: {error}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
