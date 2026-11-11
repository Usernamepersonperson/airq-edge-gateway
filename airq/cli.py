"""Command line: ``python -m airq run --mock --once --sink stdout``."""

from __future__ import annotations

import argparse
import logging
import os
from typing import Sequence

from airq.gateway import Gateway
from airq.sensor import open_sensor
from airq.sinks import HttpJsonSink, InfluxSink, MqttSink, OfflineQueue, QueuedPoster, Sink, StdoutSink

SINKS = ("stdout", "mqtt", "influx", "http")


def build_sinks(args: argparse.Namespace) -> list[Sink]:
    sinks: list[Sink] = []
    for name in args.sink:
        if name == "stdout":
            sinks.append(StdoutSink())
        elif name == "mqtt":
            sinks.append(MqttSink(args.mqtt_host, args.mqtt_port, args.device_id))
        elif name == "influx":
            sinks.append(
                InfluxSink(args.influx_target, args.device_id, args.influx_token, args.queue_path + ".influx")
            )
        elif name == "http":
            if not args.http_url:
                raise SystemExit("--sink http needs --http-url (or AIRQ_HTTP_URL)")
            poster = QueuedPoster(args.http_url, "application/json", OfflineQueue(args.queue_path))
            sinks.append(HttpJsonSink(poster))
    return sinks


def parser() -> argparse.ArgumentParser:
    env = os.environ.get
    p = argparse.ArgumentParser(prog="airq", description="Indoor air-quality edge gateway")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="read the sensor and ship measurements")
    r.add_argument("--mock", action="store_true", help="simulated I2C bus, no hardware needed")
    r.add_argument("--once", action="store_true", help="one measurement, then exit")
    r.add_argument("--seconds", type=float, help="stop after this many seconds")
    r.add_argument("--interval", type=float, default=float(env("AIRQ_INTERVAL", "5")))
    r.add_argument("--no-co2", action="store_true", help="PM/VOC/NOx sensor only (no CO2 sensor)")
    r.add_argument(
        "--sink", action="append", choices=SINKS, default=[], help="repeatable (default: stdout)"
    )
    r.add_argument("--device-id", default=env("AIRQ_DEVICE_ID", "airq-01"))
    r.add_argument("--mqtt-host", default=env("AIRQ_MQTT_HOST", "localhost"))
    r.add_argument("--mqtt-port", type=int, default=int(env("AIRQ_MQTT_PORT", "1883")))
    r.add_argument("--influx-target", default=env("AIRQ_INFLUX_TARGET", "-"),
                   help="'-' for stdout, a file path, or an InfluxDB 2 /api/v2/write URL")
    r.add_argument("--influx-token", default=env("AIRQ_INFLUX_TOKEN"))
    r.add_argument("--http-url", default=env("AIRQ_HTTP_URL"))
    r.add_argument("--queue-path", default=env("AIRQ_QUEUE_PATH", "airq-queue.sqlite"),
                   help="SQLite file buffering unsent HTTP/Influx payloads")
    r.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s"
    )
    args.sink = args.sink or ["stdout"]
    backend = "mock" if args.mock else None  # else AIRQ_BACKEND, default mock
    sensor = open_sensor(backend, with_co2=not args.no_co2)
    gateway = Gateway(sensor, build_sinks(args), args.device_id, args.interval)
    gateway.run(once=args.once, seconds=args.seconds)
    return 0
