"""Main loop: read sensor, derive, fan out to sinks."""

from __future__ import annotations

import logging
import time
from typing import Callable, Sequence

from airq.derive import Deriver
from airq.sensor import AirQualitySensor
from airq.sinks import Sink

log = logging.getLogger(__name__)


class Gateway:
    def __init__(
        self,
        sensor: AirQualitySensor,
        sinks: Sequence[Sink],
        device_id: str = "airq-01",
        interval_s: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.sensor = sensor
        self.sinks = list(sinks)
        self.device_id = device_id
        self.interval_s = interval_s
        self._sleep = sleep
        self._clock = clock
        self._deriver = Deriver()

    def tick(self) -> dict[str, object]:
        """One cycle. A failing sink is logged and never blocks the others."""
        reading = self.sensor.read(ts=self._clock())
        record = self._deriver.process(reading)
        record = {"ts": round(reading.ts, 3), "device": self.device_id, **record}
        for sink in self.sinks:
            try:
                sink.send(record)
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("sink %s failed", type(sink).__name__)
        return record

    def run(self, once: bool = False, seconds: float | None = None) -> int:
        """Run until ``once``/``seconds`` is satisfied (or forever). Returns tick count."""
        deadline = None if seconds is None else self._clock() + seconds
        ticks = 0
        try:
            self.sensor.start()
            while True:
                started = self._clock()
                try:
                    self.tick()
                    ticks += 1
                except Exception:  # noqa: BLE001 - sensor glitch: log and retry next cycle
                    log.exception("read failed")
                if once and ticks:
                    break
                if deadline is not None and started + self.interval_s >= deadline:
                    break
                self._sleep(max(0.0, self.interval_s - (self._clock() - started)))
        except KeyboardInterrupt:
            log.info("interrupted")
        finally:
            self.sensor.stop()
            for sink in self.sinks:
                sink.close()
        return ticks
