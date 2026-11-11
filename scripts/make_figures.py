"""Write docs/figure.png (1600x900) and docs/post-figure.png (960x700) from 30 minutes of mock-bus readings.

    python scripts/make_figures.py

The data are synthetic (the mock I2C bus's occupancy wave plus noise), read through the real
driver code at one sample per 5 s with a fake clock, so the run is instant and deterministic.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from airq.mock_i2c import MockI2cTransceiver
from airq.sensor import AirQualitySensor

ROOT = Path(__file__).resolve().parents[1]
BG, GRID, TEXT, MUTED = "#16213A", "#2A3750", "#F8FAFC", "#A9B6CB"
ACCENT, GREEN, AMBER, RED = "#38BDF8", "#34D399", "#FBBF24", "#F87171"
plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]


def collect(minutes: int = 30, step_s: int = 5):
    now = [0.0]
    sensor = AirQualitySensor(MockI2cTransceiver(seed=1, clock=lambda: now[0]))
    sensor.start()
    rows = []
    for i in range(minutes * 60 // step_s + 1):
        now[0] = i * step_s
        r = sensor.read(ts=now[0])
        rows.append((now[0] / 60, r.co2_ppm, r.pm2_5, r.voc_index))
    return rows


def style(ax, fs):
    ax.set_facecolor(BG)
    ax.grid(color=GRID, lw=1)
    ax.tick_params(colors=MUTED, labelsize=fs)
    for sp in ax.spines.values():
        sp.set_color(GRID)


def main() -> None:
    rows = collect()
    t = [r[0] for r in rows]
    co2 = [r[1] for r in rows]
    pm = [r[2] for r in rows]
    voc = [r[3] for r in rows]
    print(f"co2 {min(co2):.0f}..{max(co2):.0f}  pm2.5 {min(pm):.1f}..{max(pm):.1f}  voc {min(voc):.0f}..{max(voc):.0f}")

    # ---- docs/figure.png
    fig, axs = plt.subplots(3, 1, figsize=(16, 9), dpi=100, facecolor=BG, sharex=True)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.84, bottom=0.10, hspace=0.18)
    fig.text(0.02, 0.955, "Gateway output, 30 min of simulated room air", color=TEXT, fontsize=20,
             fontweight="bold")
    fig.text(0.02, 0.905, "PM / VOC / NOx + CO2 sensors → I2C → gateway → MQTT / InfluxDB / Grafana",
             color=ACCENT, fontsize=16)
    a = axs[0]
    a.axhspan(1000, 1500, color=AMBER, alpha=0.2, lw=0)
    a.axhspan(1500, 2000, color=RED, alpha=0.2, lw=0)
    a.plot(t, co2, color=TEXT, lw=2)
    a.set_ylim(300, 1800)
    a.text(7.5, 1030, "ventilate", color=AMBER, fontsize=14, ha="center")
    a.text(7.5, 1530, "ventilate now", color=RED, fontsize=14, ha="center")
    a.set_ylabel("CO₂ ppm", color=MUTED, fontsize=16)
    a = axs[1]
    a.axhline(15, color=AMBER, lw=1.5, ls="--")
    a.plot(t, pm, color=ACCENT, lw=2)
    a.set_ylim(0, 30)
    a.text(7.5, 16.2, "WHO guideline 15", color=AMBER, fontsize=14, ha="center")
    a.set_ylabel("PM2.5 µg/m³", color=MUTED, fontsize=16)
    a = axs[2]
    a.axhspan(250, 320, color=RED, alpha=0.2, lw=0)
    a.axhline(250, color=RED, lw=1.5, ls="--")
    a.plot(t, voc, color=GREEN, lw=2)
    a.set_ylim(40, 320)
    a.text(7.5, 262, "check sources > 250", color=RED, fontsize=14, ha="center")
    a.set_ylabel("VOC index", color=MUTED, fontsize=16)
    a.set_xlim(0, 30)
    a.set_xlabel("minutes", color=MUTED, fontsize=16)
    for a in axs:
        style(a, 15)
    fig.savefig(ROOT / "docs" / "figure.png", facecolor=BG)
    plt.close(fig)

    # ---- docs/post-figure.png
    fig, axs = plt.subplots(2, 1, figsize=(9.6, 7.0), dpi=100, facecolor=BG, sharex=True)
    fig.subplots_adjust(left=0.13, right=0.96, top=0.80, bottom=0.11, hspace=0.12)
    fig.text(0.04, 0.93, "Room air, as the gateway reports it", color=TEXT, fontsize=19, fontweight="bold")
    fig.text(0.04, 0.88, "Simulated data: 30 min from a mock I2C bus, no real sensor", color=MUTED, fontsize=15)
    a = axs[0]
    a.axhspan(1000, 1500, color=AMBER, alpha=0.2, lw=0)
    a.axhspan(1500, 2000, color=RED, alpha=0.2, lw=0)
    a.plot(t, co2, color=TEXT, lw=3.5)
    a.set_ylim(300, 1800)
    a.set_yticks([500, 1000, 1500])
    a.text(7.5, 1030, "ventilate", color=AMBER, fontsize=15, ha="center")
    a.text(7.5, 1540, "ventilate now", color=RED, fontsize=15, ha="center")
    a.set_ylabel("CO₂ (ppm)", color=MUTED, fontsize=15)
    a = axs[1]
    a.axhline(15, color=AMBER, lw=2.5, ls="--")
    a.plot(t, pm, color=ACCENT, lw=3.5)
    a.set_ylim(0, 30)
    a.set_yticks([0, 15, 30])
    a.text(8, 17.5, "WHO guideline 15", color=AMBER, fontsize=15, ha="center")
    a.set_ylabel("PM2.5 (µg/m³)", color=MUTED, fontsize=15)
    a.set_xlim(0, 30)
    a.set_xticks([0, 10, 20, 30])
    a.set_xlabel("minutes", color=MUTED, fontsize=15)
    for a in axs:
        style(a, 15)
        a.tick_params(labelcolor=TEXT)
    fig.savefig(ROOT / "docs" / "post-figure.png", facecolor=BG)


if __name__ == "__main__":
    main()
