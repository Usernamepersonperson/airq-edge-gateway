import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from airq.cli import main
from airq.gateway import Gateway
from airq.models import Reading
from airq.payload import encode
from airq.sensor import open_sensor

ROOT = Path(__file__).resolve().parents[1]


class ListSink:
    def __init__(self):
        self.records = []

    def send(self, record):
        self.records.append(record)

    def close(self):
        pass


class BoomSink(ListSink):
    def send(self, record):
        raise RuntimeError("down")


def test_gateway_once_and_failing_sink_does_not_block_others():
    good = ListSink()
    gw = Gateway(open_sensor("mock"), [BoomSink(), good], device_id="t1")
    assert gw.run(once=True) == 1
    rec = good.records[0]
    assert rec["device"] == "t1" and "dew_point_c" in rec and "pm2_5_24h_mean" in rec


def test_gateway_seconds_uses_interval():
    now = [0.0]
    sink = ListSink()
    gw = Gateway(open_sensor("mock"), [sink], interval_s=5, clock=lambda: now[0],
                 sleep=lambda s: now.__setitem__(0, now[0] + s))
    gw.run(seconds=30)
    assert 5 <= len(sink.records) <= 7


def test_cli_once_stdout(capsys):
    assert main(["run", "--mock", "--once"]) == 0
    rec = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rec["device"] == "airq-01" and isinstance(rec["advice"], list)


def test_python_dash_m_entrypoint():
    out = subprocess.run([sys.executable, "-m", "airq", "run", "--mock", "--once", "--sink", "influx"],
                         capture_output=True, text=True, check=True, cwd=ROOT).stdout
    assert out.startswith("airq,device=airq-01 pm1_0=")


VECTORS = json.loads((ROOT / "lorawan" / "test_vectors.json").read_text())


@pytest.mark.parametrize("v", VECTORS, ids=[v["name"] for v in VECTORS])
def test_payload_encoder_matches_shared_vectors(v):
    r = v["reading"]
    reading = Reading(ts=0, temperature_c=r.get("temperature_c"), humidity_pct=r.get("humidity_pct"),
                      co2_ppm=r.get("co2_ppm"), pm2_5=r.get("pm2_5"), pm10=r.get("pm10"),
                      voc_index=r.get("voc_index"), nox_index=r.get("nox_index"))
    assert len(encode(reading)) == 12
    assert encode(reading).hex() == v["hex"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_decoder_test_passes():
    res = subprocess.run(["node", "lorawan/test_decoder.js"], cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
