# SPDX-FileCopyrightText: 2026 flowersea123
# SPDX-License-Identifier: MIT
"""Compile and run focused display regressions; no device or network access."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = "firmware/esp32_dashboard/"


def main():
    compiler = os.environ.get("CXX", "g++")
    cases = [
        ("display_contract", ["tests/display_contract.cpp", FIRMWARE + "pages.cpp",
                              FIRMWARE + "scene.cpp", FIRMWARE + "display_scheduler.cpp"],
         ["tests/graphics_fakes", "tests/fakes"], []),
        ("display_retry", ["tests/display_retry.cpp", FIRMWARE + "scene.cpp",
                           FIRMWARE + "display_scheduler.cpp"],
         ["tests/jd79668_fakes"], []),
        ("jd79668_driver", ["tests/jd79668_driver.cpp", FIRMWARE + "gdem042f52_display.cpp"],
         ["tests/jd79668_fakes"], ["-DDASHBOARD_PANEL=2"]),
        ("fault_recovery", ["tests/fault_recovery.cpp", FIRMWARE + "scene.cpp",
                            FIRMWARE + "scene_composer.cpp", FIRMWARE + "display_scheduler.cpp",
                            FIRMWARE + "weather_adapter.cpp", FIRMWARE + "radar_adapter.cpp"],
         ["tests/fakes"], []),
    ]
    with tempfile.TemporaryDirectory(prefix="attention-display-") as directory:
        for name, sources, includes, flags in cases:
            binary = Path(directory) / (name + (".exe" if os.name == "nt" else ""))
            command = [compiler, "-std=c++17", "-Wall", "-Wextra", *flags,
                       *["-I" + str(ROOT / path) for path in includes],
                       *[str(ROOT / path) for path in sources], "-o", str(binary)]
            print("Compile and run: " + name, flush=True)
            subprocess.run(command, cwd=ROOT, check=True, timeout=120)
            subprocess.run([str(binary)], cwd=directory, check=True, timeout=30)
    print("Display regressions PASS (synthetic; not physical-screen acceptance)")


if __name__ == "__main__":
    main()
