"""Fail when a task sends a credential over HTTP without ``no_log: true``.

Ansible prints module arguments with ``-vvv`` and in failure dumps, so a
``uri`` task with an ``Authorization: Bearer {{ token }}`` header leaks the
token into terminal output, CI logs and FastDeploy step logs. This check walks
every YAML file under ``roles/`` (except molecule scenarios) and reports:

* ``uri`` tasks that send a credential: an ``Authorization``/token/API-key/
  cookie header, ``url_password``, or a request body that renders a
  secret-named variable;
* ``command``/``shell``/``raw`` tasks whose command line carries an
  ``Authorization`` header or a ``Bearer`` token (``curl -H ...``).

Such a task must have ``no_log: true``, set on the task itself or inherited
from an enclosing block or play. A templated ``no_log`` does not count: it can
evaluate to false. Keep failures debuggable with a follow-up task that prints
only ``status`` and ``json`` of the registered result; ``msg`` can quote
request headers.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]

URI_MODULES = {"uri", "ansible.builtin.uri", "ansible.legacy.uri"}
COMMAND_MODULES = {
    f"{prefix}{name}"
    for prefix in ("", "ansible.builtin.", "ansible.legacy.")
    for name in ("command", "shell", "raw")
}

SENSITIVE_HEADER = re.compile(
    r"authorization|token|api[-_]?key|secret|cookie|password", re.IGNORECASE
)
SECRET_WORD = r"(?:password|passwd|secret|token|api_key|apikey|private_key|access_key)"
# A Jinja expression mentioning a secret-named variable. Names that only point
# at a secret (``*_file``, ``*_path``, ``*_hash``, ...) do not count.
SECRET_VAR = re.compile(
    rf"\b\w*{SECRET_WORD}\w*\b(?<!_file)(?<!_path)(?<!_hash)(?<!_dir)(?<!_name)",
    re.IGNORECASE,
)
JINJA_EXPR = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
COMMAND_CREDENTIAL = re.compile(r"authorization\s*:|\bbearer\s|--oauth2-bearer", re.IGNORECASE)

TRUE_VALUES = {True, "true", "True", "yes", "Yes", "on"}


def _renders_secret(value: Any) -> bool:
    """True when a string/structure renders a secret-named Jinja variable."""
    if isinstance(value, dict):
        return any(_renders_secret(v) for v in value.values())
    if isinstance(value, list):
        return any(_renders_secret(v) for v in value)
    if not isinstance(value, str):
        return False
    return any(SECRET_VAR.search(expr) for expr in JINJA_EXPR.findall(value))


ALL_MODULES = URI_MODULES | COMMAND_MODULES


PURE_TEMPLATE = re.compile(r"^\s*\{\{.*\}\}\s*$", re.DOTALL)


def _split_free_form(text: str) -> tuple[str, str | None]:
    parts = re.split(r"\s+", text.strip(), maxsplit=1)
    return parts[0], (parts[1] if len(parts) > 1 else None)


def _module(task: dict) -> tuple[str, list[tuple[str, Any]], list[str]] | None:
    """Return (module, keyword args, free-form/templated args) for a task.

    Mirrors how Ansible assembles module arguments: the module key, an
    ``action``/``local_action`` string or mapping (``module`` may itself carry
    ``k=v`` arguments, and a nested ``args`` is flattened), and the task-level
    ``args``. Every source is kept, so a key given twice is checked twice.
    """
    module: str | None = None
    sources: list[Any] = []
    for key, value in task.items():
        if key in ALL_MODULES:
            module = key
            sources.append(value)
            break
    else:
        action = task.get("action", task.get("local_action"))
        if isinstance(action, dict):
            action = dict(action)
            name = action.pop("module", None)
            if isinstance(name, str) and name.strip():
                module, raw = _split_free_form(name)
                sources.append(raw)
            sources.append(action.pop("args", None))
            sources.append(action)
        elif isinstance(action, str) and action.strip():
            module, raw = _split_free_form(action)
            sources.append(raw)
        if module not in ALL_MODULES:
            return None
    sources.append(task.get("args"))
    pairs: list[tuple[str, Any]] = []
    raws: list[str] = []
    for source in sources:
        if isinstance(source, dict):
            for name, value in source.items():
                if name == "_raw_params" and isinstance(value, str):
                    raws.append(value)
                else:
                    pairs.append((str(name), value))
        elif isinstance(source, str) and source.strip():
            raws.append(source)
    return module, pairs, raws


def _uri_reason(pairs: list[tuple[str, Any]], raws: list[str]) -> str | None:
    for raw in raws:
        if PURE_TEMPLATE.match(raw):
            return "takes its arguments from a template that may carry credentials"
        # Free-form k=v arguments are checked as plain text, conservatively:
        # any credential-like word (Authorization, X-API-Key, Cookie,
        # url_password, ...) or secret-named variable counts.
        if SENSITIVE_HEADER.search(raw) or _renders_secret(raw):
            return "passes a credential in free-form arguments"
    for name, value in pairs:
        if name == "headers":
            if isinstance(value, dict):
                for header, header_value in value.items():
                    if SENSITIVE_HEADER.search(str(header)) or _renders_secret(header_value):
                        return f"sends header {header!r}"
            elif isinstance(value, str) and (SENSITIVE_HEADER.search(value) or _renders_secret(value)):
                return "builds headers from a credential"
        elif name == "url_password" and value not in (None, ""):
            return "sets url_password"
        elif name == "url" and _renders_secret(value):
            return "puts a secret variable in the URL"
        elif name in ("body", "src") and _renders_secret(value):
            return f"renders a secret variable into {name}"
    return None


def credential_reason(task: dict) -> str | None:
    """Return why the task sends a credential, or None."""
    found = _module(task)
    if found is None:
        return None
    module, pairs, raws = found
    if module in URI_MODULES:
        return _uri_reason(pairs, raws)
    # command/shell/raw: free-form string, cmd or argv.
    texts = list(raws)
    for name, value in pairs:
        if name == "cmd" and isinstance(value, str):
            texts.append(value)
        elif name == "argv" and isinstance(value, list):
            # Join the vector: "Bearer" and its value may be separate items.
            texts.append(" ".join(str(item) for item in value) + " ")
    if any(COMMAND_CREDENTIAL.search(text) for text in texts):
        return "passes an Authorization/Bearer credential on the command line"
    return None


def _no_log(node: dict, inherited: bool) -> bool:
    if "no_log" not in node:
        return inherited
    return node["no_log"] in TRUE_VALUES


def iter_findings(data: Any, inherited: bool = False) -> Iterator[tuple[str, str]]:
    """Yield (task name, reason) for credential tasks lacking no_log."""
    if isinstance(data, list):
        for item in data:
            yield from iter_findings(item, inherited)
        return
    if not isinstance(data, dict):
        return
    protected = _no_log(data, inherited)
    reason = credential_reason(data)
    if reason and not protected:
        yield str(data.get("name", "<unnamed task>")), reason
    for key in ("block", "rescue", "always", "tasks", "pre_tasks", "post_tasks", "handlers"):
        if key in data:
            yield from iter_findings(data[key], protected)


class _AnsibleLoader(yaml.SafeLoader):
    """SafeLoader that accepts Ansible's custom tags (``!vault``, ``!unsafe``)."""


def _construct_tagged(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


_AnsibleLoader.add_multi_constructor("!", _construct_tagged)


def _load(path: Path) -> list[Any]:
    """Load every YAML document; a parse error propagates to the caller."""
    return list(yaml.load_all(path.read_text(encoding="utf-8"), Loader=_AnsibleLoader))


def scan(paths: list[Path]) -> list[str]:
    problems = []
    for path in paths:
        try:
            shown = path.relative_to(ROOT)
        except ValueError:
            shown = path
        try:
            documents = _load(path)
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            # Never treat an unreadable file as clean.
            problems.append(f"{shown}: cannot be parsed, so it was not checked: {error}")
            continue
        for document in documents:
            for name, reason in iter_findings(document):
                problems.append(f"{shown}: task {name!r} {reason} without no_log: true")
    return problems


def default_paths() -> list[Path]:
    """Every YAML file under roles/, minus molecule scenarios.

    Molecule verify playbooks only use throwaway fixture credentials and need
    their assertion output; ``.ansible-lint`` excludes them the same way.
    """
    roles = ROOT / "roles"
    return sorted(
        p
        for p in roles.rglob("*")
        if p.suffix in {".yml", ".yaml"} and p.is_file() and "molecule" not in p.relative_to(roles).parts
    )


def main(argv: list[str]) -> int:
    paths = [Path(arg).resolve() for arg in argv] or default_paths()
    problems = scan(paths)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(
            f"\n{len(problems)} problem(s): tasks that send credentials need no_log: true. "
            "Add no_log: true and print only status and json (not msg) "
            "of the registered result in a separate task.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
