#!/usr/bin/env python3
"""Isolated Alloy -> Loki behavioral regression verification."""

from __future__ import annotations

import gzip
import json
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).parents[2]
ALLOY_IMAGE = "grafana/alloy:v1.17.1"
LOKI_IMAGE = "grafana/loki:3.3.1"
EXPECTED_LABELS = {"app", "env", "node_id", "level"}
LOKI_ENRICHMENT_LABELS = {"service_name", "detected_level"}
PII = (
    "private.person@example.com",
    "eyJabcdefghijklmnop.qwerty.signature",
    "010-1234-5678",
    "900101-1234567",
)
MASKS = ("<email>", "<jwt>", "<phone>", "<rrn>")


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
    )
    return result.stdout.strip() if capture else ""


def wait_for(url: str, predicate, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                value = response.read()
            if predicate(value):
                return value
        except Exception as error:  # service startup polling
            last_error = error
        time.sleep(0.25)
    raise TimeoutError(f"timed out waiting for {url}: {last_error}")


def loguru_record(message: str, timestamp: str) -> bytes:
    record = {
        "text": f"{message}\n",
        "record": {
            "extra": {
                "logger_name": "alloy.fixture",
                "request_id": "request-high-cardinality",
                "user_id": "user-high-cardinality",
            },
            "level": {"name": "INFO"},
            "message": message,
            "time": {"repr": timestamp},
        },
    }
    return (json.dumps(record, ensure_ascii=False) + "\n").encode()


def query_loki(port: int) -> dict:
    query = urllib.parse.urlencode({"query": '{app="krip-backend"}', "limit": "100"})
    url = f"http://127.0.0.1:{port}/loki/api/v1/query_range?{query}"
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.load(response)


def start_alloy(
    name: str,
    network: str,
    loki: str,
    logs: Path,
    data: Path,
) -> None:
    run(
        "docker", "run", "-d", "--name", name,
        "--network", network,
        "-e", "ENV=TEST",
        "-e", "NODE_ID=test-node",
        "-e", f"LOKI_URL=http://{loki}:3100/loki/api/v1/push",
        "-v", f"{ROOT / 'monitoring/alloy/config.alloy'}:/etc/alloy/config.alloy:ro",
        "-v", f"{logs}:/backend/logs:ro",
        "-v", f"{data}:/var/lib/alloy/data",
        ALLOY_IMAGE,
        "run",
        "--server.http.listen-addr=0.0.0.0:12345",
        "--storage.path=/var/lib/alloy/data",
        "/etc/alloy/config.alloy",
    )


def main() -> None:
    suffix = uuid.uuid4().hex[:10]
    network = f"hermes-alloy-{suffix}"
    loki = f"hermes-loki-{suffix}"
    alloy = f"hermes-alloy-agent-{suffix}"

    with tempfile.TemporaryDirectory(prefix="hermes-alloy-pipeline-") as temp:
        root = Path(temp)
        logs = root / "logs"
        data = root / "alloy-data"
        loki_data = root / "loki-data"
        for path in (logs, data, loki_data):
            path.mkdir()

        now = datetime.now().astimezone()
        event_times = {
            "alloy-current": now,
            "alloy-rotated": now + timedelta(microseconds=1),
            "alloy-rotation-duplicate": now + timedelta(microseconds=2),
            "alloy-after-restart": now + timedelta(microseconds=3),
        }
        pii = " | ".join(PII)
        current_marker = f"alloy-current {pii}"
        rotated_marker = f"alloy-rotated {pii}"
        duplicate_marker = "alloy-rotation-duplicate"
        restart_marker = "alloy-after-restart"
        current_log = logs / "app.log"
        rotated_log = logs / "app.2026-07-10_00-00-00.log.gz"
        current_log.write_bytes(
            loguru_record(
                current_marker,
                event_times["alloy-current"].isoformat(
                    sep=" ", timespec="microseconds"
                ),
            )
            + loguru_record(
                duplicate_marker,
                event_times[duplicate_marker].isoformat(
                    sep=" ", timespec="microseconds"
                ),
            )
        )
        with gzip.open(rotated_log, "wb") as archive:
            archive.write(
                loguru_record(
                    rotated_marker,
                    event_times["alloy-rotated"].isoformat(
                        sep=" ", timespec="microseconds"
                    ),
                )
                + loguru_record(
                    duplicate_marker,
                    event_times[duplicate_marker].isoformat(
                        sep=" ", timespec="microseconds"
                    ),
                )
            )
        current_log.chmod(0o600)
        rotated_log.chmod(0o600)

        try:
            run("docker", "network", "create", network)
            run(
                "docker", "run", "-d", "--name", loki,
                "--network", network,
                "-p", "127.0.0.1::3100",
                "-v", f"{ROOT / 'monitoring/loki/loki-config.yml'}:/etc/loki/config.yml:ro",
                "-v", f"{loki_data}:/loki",
                LOKI_IMAGE,
                "-config.file=/etc/loki/config.yml",
            )
            port_output = run("docker", "port", loki, "3100/tcp", capture=True)
            port = int(port_output.rsplit(":", 1)[1])
            wait_for(
                f"http://127.0.0.1:{port}/ready",
                lambda body: body.strip() == b"ready",
                timeout=120,
            )

            start_alloy(alloy, network, loki, logs, data)

            def has_both_entries(_: bytes = b"") -> bool:
                try:
                    payload = query_loki(port)
                except Exception:
                    return False
                lines = [
                    value[1]
                    for result in payload["data"]["result"]
                    for value in result["values"]
                ]
                return any("alloy-current" in line for line in lines) and any(
                    "alloy-rotated" in line for line in lines
                )

            wait_for(f"http://127.0.0.1:{port}/ready", has_both_entries)

            run("docker", "stop", "--time", "10", alloy)
            run("docker", "rm", alloy)
            with current_log.open("ab") as log:
                log.write(
                    loguru_record(
                        restart_marker,
                        event_times[restart_marker].isoformat(
                            sep=" ", timespec="microseconds"
                        ),
                    )
                )
            start_alloy(alloy, network, loki, logs, data)

            def has_restart_entry(_: bytes = b"") -> bool:
                try:
                    payload = query_loki(port)
                except Exception:
                    return False
                return any(
                    restart_marker in value[1]
                    for result in payload["data"]["result"]
                    for value in result["values"]
                )

            wait_for(f"http://127.0.0.1:{port}/ready", has_restart_entry)
            payload = query_loki(port)
            results = payload["data"]["result"]
            lines = [value[1] for result in results for value in result["values"]]
            timestamps = [value[0] for result in results for value in result["values"]]
            streams = [result["stream"] for result in results]

            assert any("alloy-current" in line for line in lines)
            assert any("alloy-rotated" in line for line in lines)
            assert any(restart_marker in line for line in lines)
            assert sum(duplicate_marker in line for line in lines) == 1
            assert all(secret not in "\n".join(lines) for secret in PII)
            assert all(mask in "\n".join(lines) for mask in MASKS)
            assert timestamps
            assert len(timestamps) == len(lines)
            for marker, event_time in event_times.items():
                expected_ns = str(int(event_time.timestamp() * 1_000_000) * 1000)
                marker_timestamps = {
                    timestamp
                    for timestamp, line in zip(timestamps, lines)
                    if marker in line
                }
                assert marker_timestamps == {expected_ns}
            for stream in streams:
                labels = set(stream)
                assert EXPECTED_LABELS <= labels, stream
                assert labels - EXPECTED_LABELS <= LOKI_ENRICHMENT_LABELS, stream
                assert stream["app"] == "krip-backend"
                assert stream["env"] == "TEST"
                assert stream["node_id"] == "test-node"
                assert stream["level"] == "INFO"
                assert stream.get("service_name", "krip-backend") == "krip-backend"
                assert stream.get("detected_level", "INFO") == "INFO"
                assert not labels & {"filename", "request_id", "user_id", "logger_name"}

            print("ALLOY_PIPELINE_E2E_PASS")
        except Exception:
            subprocess.run(["docker", "logs", loki], check=False)
            subprocess.run(["docker", "logs", alloy], check=False)
            raise
        finally:
            subprocess.run(
                ["docker", "rm", "-f", alloy, loki],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            subprocess.run(
                ["docker", "network", "rm", network],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


if __name__ == "__main__":
    main()
