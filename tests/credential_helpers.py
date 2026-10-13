"""Credential delivery regressions; no host or database access."""
from pathlib import Path

import yaml
from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ENV = Environment(undefined=StrictUndefined)
ENV.filters.update(FilterModule().filters())


def tasks(role, file):
    def walk(nodes):
        for task in nodes:
            yield task
            for key in ('block', 'rescue', 'always'):
                yield from walk(task.get(key, []))
    return list(walk(yaml.safe_load((ROOT / 'roles' / role / 'tasks' / file).read_text())))
