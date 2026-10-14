"""Keep hashing inputs out of process arguments and Ansible task environment."""

import json
import re
import subprocess
import sys

inputs = json.load(sys.stdin)
candidates = [
    line for line in inputs["existing_hash"].splitlines() if line.startswith("$6$")
]
existing = candidates[-1] if candidates else ""
command = ["mkpasswd", "-m", "sha-512"]
rounds = re.match(r"^\$6\$rounds=([0-9]+)\$([^$]+)\$", existing)
salt = re.match(r"^\$6\$([^$]+)\$", existing)
if rounds:
    command += ["-R", rounds[1], "-S", rounds[2]]
elif salt:
    command += ["-S", salt[1]]
command += ["--stdin"]
result = subprocess.run(command, check=False, input=inputs["password"], text=True)
sys.exit(result.returncode)
