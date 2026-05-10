from __future__ import annotations

import re

_SENSITIVE_KEY = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|AUTH)", re.I)


def redact_env_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY.search(key))


def redact_line(line: str) -> str:
    if "=" in line and redact_env_key(line.split("=", 1)[0]):
        k, _, _v = line.partition("=")
        return f"{k}=***REDACTED***"
    return line
