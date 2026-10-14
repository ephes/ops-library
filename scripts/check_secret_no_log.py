"""Fail when a task passes a credential in its arguments without ``no_log: true``.

Ansible prints module arguments with ``-vvv`` and in failure dumps, so a
``uri`` task with an ``Authorization: Bearer {{ token }}`` header leaks the
token into terminal output, CI logs and FastDeploy step logs. A ``command``
task prints its command line in every failure result even without ``-v``.
This check walks every YAML file under ``roles/`` (except molecule scenarios)
and reports:

* ``uri`` tasks that send a credential: an ``Authorization``/token/API-key/
  cookie header, ``url_password``, or a request body that renders a
  secret-named variable;
* ``postgresql_query`` tasks that read or write password-bearing columns or
  known password-bearing tables (`admin`, `mail_users`, `mailbox`),
  including password hashes;
* ``command``/``shell``/``raw`` tasks whose command line carries an
  ``Authorization`` header or a ``Bearer`` token (``curl -H ...``);
* ``command``/``shell``/``raw`` tasks that render a secret-named variable
  (``{{ admin_password }}``, ``{{ rcon_password }}``, ...) into the command
  line or into ``stdin``.

A secret on a command line or in task ``environment:`` is also exposed by
remote shell argv/connection logging, regardless of ``no_log``. The additional
``--exposure`` check rejects these delivery paths even when logging is hidden.
Use stdin (with no_log) or a private 0600 file read inside the remote command.

Such a task must have ``no_log: true``, set on the task itself or inherited
from an enclosing block or play. A templated ``no_log`` does not count: it can
evaluate to false. Keep failures debuggable with a follow-up task that prints
only ``status`` and ``json`` of the registered result; ``msg`` can quote
request headers.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
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
    r"authorization|token|api[-_]?key|secret|cookie|password|passphrase", re.IGNORECASE
)
SECRET_WORD = r"(?:password|passwd|secret|token|api_key|apikey|private_key|access_key|auth_?key)"
# A Jinja expression mentioning a secret-named variable. Names that only point
# at a secret (``*_file``, ``*_path``, ``*_hash``, ...) do not count.
SECRET_VAR = re.compile(
    rf"\b\w*{SECRET_WORD}\w*\b(?<!_file)(?<!_path)(?<!_hash)(?<!_dir)(?<!_name)",
    re.IGNORECASE,
)
JINJA_EXPR = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
STRING_LITERAL = re.compile(r"""'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*\"""")
COMMAND_CREDENTIAL = re.compile(
    r"authorization\s*:|\bbearer\s|--oauth2-bearer", re.IGNORECASE
)

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


def _renders_secret_variable(value: Any) -> bool:
    """Like ``_renders_secret``, but ignores string literals in expressions.

    A command legitimately names files and options that contain words such as
    ``token`` (``lookup('file', 'service_token_status.py')``); only a variable
    with a secret-like name counts here.
    """
    if isinstance(value, dict):
        return any(_renders_secret_variable(v) for v in value.values())
    if isinstance(value, list):
        return any(_renders_secret_variable(v) for v in value)
    if not isinstance(value, str):
        return False
    return any(
        SECRET_VAR.search(STRING_LITERAL.sub("''", expr))
        for expr in JINJA_EXPR.findall(value)
    )


QUERY_MODULES = {"postgresql_query", "community.postgresql.postgresql_query"}
ALL_MODULES = URI_MODULES | COMMAND_MODULES | QUERY_MODULES


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
                    if SENSITIVE_HEADER.search(str(header)) or _renders_secret(
                        header_value
                    ):
                        return f"sends header {header!r}"
            elif isinstance(value, str) and (
                SENSITIVE_HEADER.search(value) or _renders_secret(value)
            ):
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
    if module in QUERY_MODULES:
        # login_password is redacted by the module; query arguments and rows
        # are not. Password hashes are credentials too.
        for name, value in pairs:
            if name in {"query", "named_args", "positional_args"} and (
                SENSITIVE_HEADER.search(str(value))
                or re.search(
                    r"\b(?:from|into|update)\s+[\"]?(?:admin|mail_users|mailbox)\b",
                    str(value),
                    re.IGNORECASE,
                )
            ):
                return "queries password-bearing data"
        if raws:
            return "takes query arguments in free-form form"
        return None
    if module in URI_MODULES:
        return _uri_reason(pairs, raws)
    # command/shell/raw: free-form string, cmd or argv.
    texts = list(raws)
    stdin: list[Any] = []
    for name, value in pairs:
        if name == "cmd" and isinstance(value, str):
            texts.append(value)
        elif name == "argv" and isinstance(value, list):
            # Join the vector: "Bearer" and its value may be separate items.
            texts.append(" ".join(str(item) for item in value) + " ")
        elif name == "argv" and isinstance(value, str):
            texts.append(value)
        elif name == "stdin":
            stdin.append(value)
    if any(COMMAND_CREDENTIAL.search(text) for text in texts):
        return "passes an Authorization/Bearer credential on the command line"
    if any(_renders_secret_variable(text) for text in texts):
        return "renders a secret-named variable into the command line"
    if any(_renders_secret_variable(value) for value in stdin):
        return "renders a secret-named variable into stdin"
    return None


def _renders_exposure_secret(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_renders_exposure_secret(v) for v in value.values())
    if isinstance(value, list):
        return any(_renders_exposure_secret(v) for v in value)
    if not isinstance(value, str):
        return False
    pattern = re.compile(
        r"\b\w*(?:password|passwd|passphrase|secret|token|api_key|apikey|private_key|access_key|auth_?key)\w*\b"
        r"(?<!_file)(?<!_path)(?<!_dir)(?<!_name)",
        re.IGNORECASE,
    )
    return any(
        pattern.search(STRING_LITERAL.sub("''", expr))
        for expr in JINJA_EXPR.findall(value)
    )


def _environment_reason(environment: Any) -> str | None:
    # A list holds inherited layers (block environments, then the task's own),
    # or is Ansible's own list-of-mappings form; every layer reaches the process.
    if isinstance(environment, list):
        for layer in environment:
            reason = _environment_reason(layer)
            if reason:
                return reason
        return None
    if isinstance(environment, dict):
        for key, value in environment.items():
            if value in (None, ""):
                continue
            if _renders_exposure_secret(value) or (
                SENSITIVE_HEADER.search(str(key))
                and not str(key).upper().endswith(("_FILE", "_PATH", "_DIR"))
            ):
                return "puts a credential in task environment"
        return None
    if _renders_exposure_secret(environment):
        return "builds task environment from a credential"
    return None


def exposure_reason(task: dict, environment: Any = None) -> str | None:
    """Reject credentials in connection-level environment or process arguments.

    Unlike credential_reason, no_log never suppresses these findings. stdin
    and credential-file module content remain covered by their logging/mode
    checks; a path is not a credential.
    """
    if environment is None:
        environment = task.get("environment")
    reason = _environment_reason(environment)
    if reason:
        return reason
    found = _module(task)
    if found is None or found[0] not in COMMAND_MODULES:
        return None
    _, pairs, raws = found
    texts = list(raws) + [value for name, value in pairs if name in {"cmd", "argv"}]
    if any(_renders_exposure_secret(value) for value in texts):
        return "puts a secret-named variable in command arguments"
    if any(COMMAND_CREDENTIAL.search(str(value)) for value in texts):
        return "puts an Authorization/Bearer credential in command arguments"
    return None


def iter_exposure_findings(
    data: Any, environment: Any = None
) -> Iterator[tuple[str, str]]:
    if isinstance(data, list):
        for item in data:
            yield from iter_exposure_findings(item, environment)
        return
    if not isinstance(data, dict):
        return
    # Keep every ancestor environment: a child environment given as a template
    # or list does not stop Ansible from passing the inherited values. Only two
    # mappings merge (child keys override parent keys, as in Ansible).
    current = list(environment or [])
    if "environment" in data:
        own = data["environment"]
        if current and isinstance(current[-1], dict) and isinstance(own, dict):
            current[-1] = {**current[-1], **own}
        else:
            current.append(own)
    children = [
        key
        for key in (
            "block",
            "rescue",
            "always",
            "tasks",
            "pre_tasks",
            "post_tasks",
            "handlers",
        )
        if key in data
    ]
    if not children:
        reason = exposure_reason(data, current)
        if reason:
            yield str(data.get("name", "<unnamed task>")), reason
    for key in children:
        yield from iter_exposure_findings(data[key], current)


def exposure_scan(paths: list[Path]) -> list[tuple[str, str, str]]:
    """Return exact file/task/reason identities for rollout and regression checks."""
    findings = []
    for path in paths:
        shown = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        try:
            documents = _load(path)
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            findings.append((shown, "<parse failure>", str(error)))
            continue
        for document in documents:
            findings.extend(
                (shown, name, reason)
                for name, reason in iter_exposure_findings(document)
            )
    return findings


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
    for key in (
        "block",
        "rescue",
        "always",
        "tasks",
        "pre_tasks",
        "post_tasks",
        "handlers",
    ):
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
            problems.append(
                f"{shown}: cannot be parsed, so it was not checked: {error}"
            )
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
        if p.suffix in {".yml", ".yaml"}
        and p.is_file()
        and "molecule" not in p.relative_to(roles).parts
    )


def main(argv: list[str]) -> int:
    if "--exposure" in argv:
        import json

        argv = [arg for arg in argv if arg != "--exposure"]
        paths = [Path(arg).resolve() for arg in argv] or default_paths()
        baseline = json.loads(
            (ROOT / "scripts/secret_exposure_allowlist.json").read_text()
        )
        allowed = Counter(
            (entry["file"], entry["task"], entry["reason"]) for entry in baseline
        )
        problems = []
        for finding in exposure_scan(paths):
            if allowed[finding]:
                allowed[finding] -= 1
            else:
                problems.append(finding)
        if not argv:
            for finding, remaining in allowed.items():
                problems.extend(
                    (finding[0], finding[1], "has a stale exposure allowlist entry")
                    for _ in range(remaining)
                )
        for file, task, reason in problems:
            remediation = (
                "remove the stale entry from scripts/secret_exposure_allowlist.json"
                if reason == "has a stale exposure allowlist entry"
                else "use stdin or a 0600 file"
            )
            print(f"{file}: task {task!r} {reason}; {remediation}", file=sys.stderr)
        return int(bool(problems))
    paths = [Path(arg).resolve() for arg in argv] or default_paths()
    problems = scan(paths)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(
            f"\n{len(problems)} problem(s): tasks that send credentials need no_log: true. "
            "For uri, add no_log: true and print only status and json (not msg) "
            "of the registered result in a separate task. For command/shell, "
            "move the secret off the command line (stdin or a 0600 file) and "
            "add no_log: true.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
