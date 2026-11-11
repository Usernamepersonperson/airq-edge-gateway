"""Output sinks: stdout JSON, MQTT, InfluxDB line protocol, HTTP JSON uplink.

A sink receives one flat record dict per sample (see ``airq.derive``).
HTTP-based sinks never drop data: each body is written to a SQLite queue first
and removed only after the server answers 2xx, so an outage just means the
queue grows and is drained (oldest first) when the uplink returns.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Protocol

log = logging.getLogger(__name__)

Record = dict[str, Any]


class Sink(Protocol):
    def send(self, record: Record) -> None: ...
    def close(self) -> None: ...


# --------------------------------------------------------------------------
# InfluxDB line protocol
# --------------------------------------------------------------------------
def _esc(text: str, chars: str) -> str:
    text = text.replace("\\", "\\\\")
    for ch in chars:
        text = text.replace(ch, "\\" + ch)
    return text


def line_protocol(
    measurement: str, tags: dict[str, str], fields: dict[str, Any], ts_ns: int
) -> str:
    """Build one line: ``m,tag=v field=1.5,n=3i,s="x" 1700000000000000000``.

    Escaping per the InfluxDB docs: measurement escapes comma/space; tag keys,
    tag values and field keys escape comma/equals/space; string field values
    escape double quote and backslash. bool -> t/f, int -> 'i' suffix.
    """
    head = _esc(measurement, ", ")
    for k in sorted(tags):
        head += f",{_esc(k, ',= ')}={_esc(str(tags[k]), ',= ')}"
    parts = []
    for k, v in fields.items():
        if v is None:
            continue
        if isinstance(v, bool):
            enc = "t" if v else "f"
        elif isinstance(v, int):
            enc = f"{v}i"
        elif isinstance(v, float):
            enc = repr(v)
        else:
            enc = '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
        parts.append(f"{_esc(k, ',= ')}={enc}")
    if not parts:
        raise ValueError("line protocol needs at least one field")
    return f"{head} {','.join(parts)} {ts_ns}"


def record_to_line(record: Record, device_id: str, ts: float) -> str:
    fields = {
        k: v for k, v in record.items() if isinstance(v, (int, float)) and k != "ts"
    }
    advice = record.get("advice")
    if advice:
        fields["advice"] = "; ".join(advice)
    return line_protocol("airq", {"device": device_id}, fields, int(round(ts * 1000)) * 1_000_000)


# --------------------------------------------------------------------------
# Offline buffer + HTTP uploader
# --------------------------------------------------------------------------
class OfflineQueue:
    """FIFO of pending request bodies in SQLite (survives restarts)."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS q (id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL)"
        )
        self._db.commit()

    def push(self, body: str) -> None:
        self._db.execute("INSERT INTO q (body) VALUES (?)", (body,))
        self._db.commit()

    def peek(self, limit: int = 50) -> list[tuple[int, str]]:
        return list(self._db.execute("SELECT id, body FROM q ORDER BY id LIMIT ?", (limit,)))

    def delete(self, row_id: int) -> None:
        self._db.execute("DELETE FROM q WHERE id = ?", (row_id,))
        self._db.commit()

    def __len__(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM q").fetchone()[0])

    def close(self) -> None:
        self._db.close()


class QueuedPoster:
    """POST bodies to a URL with retry; failures leave the body in the queue."""

    def __init__(
        self,
        url: str,
        content_type: str,
        queue: OfflineQueue,
        headers: dict[str, str] | None = None,
        retries: int = 2,
        backoff_s: float = 0.5,
        timeout_s: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.url = url
        self.queue = queue
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.retries = retries
        self.backoff_s = backoff_s
        self.timeout_s = timeout_s
        self._sleep = sleep

    def _post_once(self, body: str) -> bool:
        req = urllib.request.Request(
            self.url, data=body.encode("utf-8"), headers=self.headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, OSError) as exc:
            log.warning("POST %s failed: %s", self.url, exc)
            return False

    def _post(self, body: str) -> bool:
        for attempt in range(self.retries + 1):
            if self._post_once(body):
                return True
            if attempt < self.retries:
                self._sleep(self.backoff_s * 2**attempt)
        return False

    def submit(self, body: str) -> int:
        """Queue the body, then drain. Returns how many items are still pending."""
        self.queue.push(body)
        return self.flush()

    def flush(self) -> int:
        while True:
            batch = self.queue.peek()
            if not batch:
                return 0
            for row_id, body in batch:
                if not self._post(body):
                    return len(self.queue)  # still down: keep order, try next cycle
                self.queue.delete(row_id)


# --------------------------------------------------------------------------
# Sinks
# --------------------------------------------------------------------------
class StdoutSink:
    def __init__(self, stream: Any = None) -> None:
        self._stream = stream or sys.stdout

    def send(self, record: Record) -> None:
        print(json.dumps(record, separators=(",", ":")), file=self._stream, flush=True)

    def close(self) -> None:
        pass


class HttpJsonSink:
    """Generic uplink: POST the record as JSON (offline-buffered)."""

    def __init__(self, poster: QueuedPoster) -> None:
        self.poster = poster

    def send(self, record: Record) -> None:
        pending = self.poster.submit(json.dumps(record, separators=(",", ":")))
        if pending:
            log.warning("uplink down, %d record(s) buffered", pending)

    def close(self) -> None:
        self.poster.queue.close()


class InfluxSink:
    """Line protocol to stdout ('-'), a file path, or an http(s) write endpoint.

    For InfluxDB 2 the URL looks like
    ``http://host:8086/api/v2/write?org=ORG&bucket=BUCKET&precision=ns`` with
    ``Authorization: Token <token>``. HTTP writes are offline-buffered.
    """

    def __init__(
        self, target: str, device_id: str, token: str | None = None, queue_path: str = ":memory:"
    ) -> None:
        self.device_id = device_id
        self._poster: QueuedPoster | None = None
        self._path: Path | None = None
        if target.startswith(("http://", "https://")):
            headers = {"Authorization": f"Token {token}"} if token else {}
            self._poster = QueuedPoster(
                target, "text/plain; charset=utf-8", OfflineQueue(queue_path), headers
            )
        elif target != "-":
            self._path = Path(target)

    def send(self, record: Record) -> None:
        line = record_to_line(record, self.device_id, float(record["ts"]))
        if self._poster:
            pending = self._poster.submit(line)
            if pending:
                log.warning("influx down, %d line(s) buffered", pending)
        elif self._path:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        else:
            print(line, flush=True)

    def close(self) -> None:
        if self._poster:
            self._poster.queue.close()


class MqttSink:
    """Publish the record as JSON to ``<prefix>/<device_id>/state`` (paho-mqtt)."""

    def __init__(self, host: str, port: int, device_id: str, prefix: str = "airq") -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:  # optional dependency
            raise RuntimeError("MQTT sink needs paho-mqtt: pip install .[mqtt]") from exc
        self.topic = f"{prefix}/{device_id}/state"
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.connect(host, port, keepalive=60)
        self._client.loop_start()

    def send(self, record: Record) -> None:
        info = self._client.publish(self.topic, json.dumps(record), qos=1)
        info.wait_for_publish(timeout=5)

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
