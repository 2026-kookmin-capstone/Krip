import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[4]
MONITORING = ROOT / "monitoring"
MAKEFILE = MONITORING / "Makefile"


def test_health_uses_http_error_failing_curl_options():
    result = subprocess.run(
        ["make", "-n", "-f", str(MAKEFILE), "health"],
        cwd=MONITORING,
        check=True,
        capture_output=True,
        text=True,
    )

    commands = [line for line in result.stdout.splitlines() if "curl " in line]
    assert len(commands) == 1
    assert "--show-error" in commands[0]
    assert "--output" in commands[0]
    assert "--write-out" in commands[0]
    assert result.stdout.count("check '") == 3


@pytest.mark.parametrize(
    ("failed_path", "http_status", "expected_calls"),
    [
        ("/health", 302, 1),
        ("/health/deep", 302, 2),
        ("/ready", 302, 3),
        ("/health", 503, 1),
        ("/health/deep", 503, 2),
        ("/ready", 503, 3),
    ],
)
def test_health_fails_fast_when_any_endpoint_is_non_2xx(
    tmp_path: Path,
    failed_path: str,
    http_status: int,
    expected_calls: int,
):
    call_log = tmp_path / "curl-calls"
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

url = sys.argv[-1]
with Path(os.environ["CURL_CALL_LOG"]).open("a") as log:
    log.write(url + "\\n")
status = int(os.environ["HTTP_STATUS"]) if url.endswith(os.environ["FAIL_PATH"]) else 200
if "--output" in sys.argv:
    Path(sys.argv[sys.argv.index("--output") + 1]).write_text("response-body")
print(status, end="")
""",
    )
    fake_curl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "CURL_CALL_LOG": str(call_log),
        "FAIL_PATH": failed_path,
        "HTTP_STATUS": str(http_status),
    }

    result = subprocess.run(
        ["make", "-s", "-f", str(MAKEFILE), "health"],
        cwd=MONITORING,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert len(call_log.read_text().splitlines()) == expected_calls
