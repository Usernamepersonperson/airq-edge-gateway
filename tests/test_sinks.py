import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from airq.sinks import (
    HttpJsonSink,
    InfluxSink,
    OfflineQueue,
    QueuedPoster,
    line_protocol,
    record_to_line,
)


# -- line protocol -------------------------------------------------------
def test_line_protocol_basic():
    line = line_protocol("airq", {"device": "a1"}, {"co2": 800.5, "n": 3, "ok": True}, 42)
    assert line == "airq,device=a1 co2=800.5,n=3i,ok=t 42"


def test_line_protocol_escaping():
    line = line_protocol(
        "my meas,x",
        {"loc ation": "room=1, 2"},
        {"fie ld": 'say "hi" \\ there', "none": None},
        1,
    )
    assert line == (
        'my\\ meas\\,x,loc\\ ation=room\\=1\\,\\ 2 '
        'fie\\ ld="say \\"hi\\" \\\\ there" 1'
    )


def test_line_protocol_needs_a_field():
    with pytest.raises(ValueError):
        line_protocol("m", {}, {"a": None}, 1)


def test_record_to_line_ms_timestamp_and_advice():
    rec = {"ts": 1700000000.123, "device": "x", "co2_ppm": 1200.0, "advice": ["a", "b"]}
    assert record_to_line(rec, "x", rec["ts"]) == (
        'airq,device=x co2_ppm=1200.0,advice="a; b" 1700000000123000000'
    )


def test_influx_sink_file(tmp_path):
    path = tmp_path / "out.lp"
    sink = InfluxSink(str(path), "dev")
    sink.send({"ts": 1.0, "co2_ppm": 500.0, "advice": []})
    sink.send({"ts": 2.0, "co2_ppm": 600.0, "advice": []})
    assert path.read_text().splitlines() == [
        "airq,device=dev co2_ppm=500.0 1000000000",
        "airq,device=dev co2_ppm=600.0 2000000000",
    ]


# -- offline buffer ------------------------------------------------------
class _Collector:
    def __init__(self):
        self.bodies: list[str] = []
        self.auth: list[str | None] = []


def _server(collector: _Collector):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            collector.bodies.append(self.rfile.read(n).decode())
            collector.auth.append(self.headers.get("Authorization"))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _free_port() -> int:
    srv = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = srv.server_port
    srv.server_close()
    return port


def _poster(url, queue, **kw):
    return QueuedPoster(url, "application/json", queue, retries=1, backoff_s=0, timeout_s=1,
                        sleep=lambda s: None, **kw)


def test_http_sink_buffers_when_down_and_flushes_when_back(tmp_path):
    port = _free_port()
    url = f"http://127.0.0.1:{port}/ingest"
    queue = OfflineQueue(tmp_path / "q.sqlite")
    sink = HttpJsonSink(_poster(url, queue))

    # Uplink down: nothing delivered, everything queued, nothing lost.
    for i in range(3):
        sink.send({"seq": i})
    assert len(queue) == 3

    # Uplink returns on the same port.
    got = _Collector()

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            got.bodies.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        sink.send({"seq": 3})
    finally:
        srv.shutdown()
    assert [json.loads(b)["seq"] for b in got.bodies] == [0, 1, 2, 3]  # in order
    assert len(queue) == 0


def test_queue_survives_restart(tmp_path):
    path = tmp_path / "q.sqlite"
    q1 = OfflineQueue(path)
    q1.push("a")
    q1.close()
    assert [b for _, b in OfflineQueue(path).peek()] == ["a"]


def test_server_error_keeps_item_queued():
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(500)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        queue = OfflineQueue()
        assert _poster(f"http://127.0.0.1:{srv.server_port}/", queue).submit("x") == 1
    finally:
        srv.shutdown()


def test_influx_http_sink_sends_token_and_line():
    got = _Collector()
    srv = _server(got)
    try:
        sink = InfluxSink(f"http://127.0.0.1:{srv.server_port}/api/v2/write", "d", token="tok")
        sink.send({"ts": 1.0, "co2_ppm": 500.0, "advice": []})
    finally:
        srv.shutdown()
    assert got.bodies == ["airq,device=d co2_ppm=500.0 1000000000"]
    assert got.auth == ["Token tok"]
