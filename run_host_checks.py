# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Run the V1 host regression suite without network access or hardware.

Requires Python 3.11+ and g++ with C++17. The Hub parser test uses an installed
ArduinoJson source tree when available, otherwise its json-c compatibility shim.
The ESP32 target build and physical panel/WAN tests are separate acceptance steps.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / ".build"


def run(name: str, command: list[str], cwd: Path | None = None) -> None:
    print(f"\n== {name} ==", flush=True)
    completed = subprocess.run(command, cwd=cwd or ROOT, text=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"{name} failed with exit code {completed.returncode}")


def compile_and_run(name: str, sources: list[str], includes: list[str], libs: list[str] | None = None) -> None:
    binary = BUILD / name
    command = [
        "g++",
        "-std=c++17",
        "-Wall",
        "-Wextra",
        *[f"-I{ROOT / include}" for include in includes],
        *[str(ROOT / source) for source in sources],
        *(libs or []),
        "-o",
        str(binary),
    ]
    run(f"compile {name}", command)
    run(name, [str(binary)])


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    print("Python suite", flush=True)
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "hub", "-v"],
        cwd=ROOT,
        env=env,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return completed.returncode

    compile_and_run(
        "cache_recovery",
        ["tests/cache_recovery.cpp", "firmware/esp32_dashboard/scene_cache.cpp", "firmware/esp32_dashboard/scene.cpp"],
        ["tests/fakes"],
    )
    compile_and_run(
        "fault_recovery",
        [
            "tests/fault_recovery.cpp",
            "firmware/esp32_dashboard/scene.cpp",
            "firmware/esp32_dashboard/scene_composer.cpp",
            "firmware/esp32_dashboard/display_scheduler.cpp",
            "firmware/esp32_dashboard/weather_adapter.cpp",
            "firmware/esp32_dashboard/radar_adapter.cpp",
        ],
        ["tests/fakes"],
    )
    compile_and_run(
        "display_contract",
        [
            "tests/display_contract.cpp",
            "firmware/esp32_dashboard/scene.cpp",
            "firmware/esp32_dashboard/display_scheduler.cpp",
            "firmware/esp32_dashboard/pages.cpp",
        ],
        ["tests/graphics_fakes", "tests/fakes", "firmware/esp32_dashboard"],
    )
    compile_and_run(
        "radar_detail",
        ["tests/radar_detail.cpp", "firmware/esp32_dashboard/radar_adapter.cpp"],
        ["tests/fakes"],
    )
    compile_and_run(
        "authority_state",
        [
            "tests/authority_state.cpp",
            "firmware/esp32_dashboard/connectivity_manager.cpp",
            "firmware/esp32_dashboard/scene.cpp",
        ],
        ["tests/fakes"],
    )
    arduinojson_src = Path(os.environ.get("ARDUINOJSON_SRC", "")) if os.environ.get("ARDUINOJSON_SRC") else (
        Path.home() / "Documents" / "Arduino" / "libraries" / "ArduinoJson" / "src"
    )
    parser_includes = ([str(arduinojson_src)] if (arduinojson_src / "ArduinoJson.h").is_file()
                       else ["tests/parser_fakes"])
    parser_libs = [] if parser_includes[0] != "tests/parser_fakes" else ["-ljson-c"]
    compile_and_run(
        "hub_parser",
        [
            "tests/hub_parser.cpp",
            "firmware/esp32_dashboard/hub_client.cpp",
            "firmware/esp32_dashboard/scene.cpp",
        ],
        [*parser_includes, "tests/fakes"],
        parser_libs,
    )
    print("\nAll host checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
