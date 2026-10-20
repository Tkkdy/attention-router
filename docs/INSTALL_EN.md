<!-- SPDX-FileCopyrightText: 2026 Tkkdy -->
<!-- SPDX-License-Identifier: MIT -->
# Windows installation and ESP32 hardware guide

[English overview](../README_EN.md) · [中文安装说明](WINDOWS.md) · [中文硬件说明](HARDWARE.md)

This guide covers the published v0.1.0 source release. You can run the Web Console without a device, Bot or model. The hardware sections are instructions for your own approved test hardware; **those instructions are not proof of hardware acceptance**. The exact public firmware still needs safe core hardware acceptance. Historical software tests and private-device observations do not prove that acceptance.

Use compatible test hardware, a separate test network and synthetic tasks. Commands below do not authorize changes to an existing service, device or its data. This candidate contains source only, not ready-to-flash firmware.

## 1. Hardware identity, pinout and power

The source target is **classic ESP32 / `esp32:esp32:esp32`, 4 MB Flash**, with a **GDEY042Z98 4.2-inch, 400 × 300, black/white/red panel (SSD1683)** and a matching SPI adapter. The source instantiates `GxEPD2_420c_GDEY042Z98`. Historical records name ESP32 DevKitC V4 / ESP32-WROOM-32E; the actual board and adapter must still be identified physically. Other 4.2-inch panels are not automatically interchangeable. **Seeed XIAO ESP32S3 is not a launch target.**

These pin numbers come from [config.h](../firmware/esp32_dashboard/config.h), and the driver wiring is in [pages.cpp](../firmware/esp32_dashboard/pages.cpp):

| Adapter signal | Classic ESP32 connection |
| --- | --- |
| BUSY | GPIO 4 |
| CS | GPIO 5 |
| RST | GPIO 16 |
| DC | GPIO 17 |
| SCK / CLK | GPIO 18 |
| MOSI / DIN | GPIO 23 |
| GND | Common ground |
| VCC | **Unspecified until the exact adapter and its documented input voltage are confirmed** |

**Disconnect power before wiring. Do not connect adapter VCC until its model, input voltage and power requirements have been verified.** ESP32 GPIO uses 3.3 V logic; never apply 5 V to those GPIOs or assume a bare panel tolerates 5 V. Use a suitable panel adapter/driver board, not a direct GPIO connection to the bare FPC. GxEPD2's bare-display guidance is 3.3 V supply and data; that does not establish the input specification of an unknown adapter with possible regulation/level shifting. USB power to the ESP32 does **not** imply 5 V is appropriate for the display's VCC. No adapter current rating or 5 V compatibility is inferred here.

Before powering or flashing, physically confirm the board/module marking, Flash capacity, panel marking, adapter model, supply specification, logic levels, common ground and every signal connection. These confirmations remain outstanding for the final candidate; the table is a source-to-wire reference, not evidence of a completed hardware test.

## 2. Fresh Windows Hub installation

Use a new extracted source directory and open PowerShell at its root. Use Windows with Python 3.13; historical software validation used Python 3.13.7. If Python is missing, install it from the [official Python downloads](https://www.python.org/downloads/windows/) and check `py -0p`. Do not reuse a personal database or change another project's interpreter.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip check
Copy-Item config.example.json config.local.json
.\.venv\Scripts\python.exe hub\run_preview.py
```

These copy commands assume a fresh directory. If a local configuration already exists, inspect it instead of overwriting it. Dependency/tool downloads need Internet access, although basic Hub operation needs no model, Bot, domain, Tunnel or subscription.

Open <http://127.0.0.1:8765/> on the same PC. The default is loopback-only; the Console establishes a local session. Data is stored under this source directory's `.build/preview-data/`. Stop only this Hub with `Ctrl+C` in its terminal; the next start reuses its data. No system service or startup registration is installed.

In a second PowerShell at the same root:

```powershell
.\.venv\Scripts\python.exe examples\local_demo.py
```

The example **adds** synthetic Todo, Current and reminder data; repeated runs add more examples. ACK in the Console clears the reminder without completing the Todo. A manual CODING override supplies work context; it does not override every alert or prove Agent task completion. TODAY means the first three pending tasks in existing order, not a date filter.

### Connect the new Hub to a trusted test LAN

Only `port`, `device_host` and `monitor` are accepted by the basic configuration. For example:

```json
{"port":8765,"device_host":null,"monitor":true}
```

`device_host` is the **PC's listening address**, not the ESP32's address. For a device connection, replace `null` with the PC's actual private LAN IPv4 on the intended adapter. It must be an explicit RFC1918 IPv4, not `0.0.0.0`, a hostname or a public IP. Use `ipconfig` to identify it; do not assume the example address in the firmware template exists. Restart only this new Hub after changing its configuration. Match the same PC IP and port in `DASHBOARD_HUB_URL` below. Use a 2.4 GHz Wi-Fi network reachable from that PC.

If the port is occupied, choose an unused port and update the Hub, firmware URL and demo's `--url http://127.0.0.1:YOUR_PORT` option. Do not terminate unrelated processes. If Windows Firewall needs a rule, the owner should restrict it to the trusted Private network and intended device source; this guide does not automatically open ports. Anonymous LAN clients may read `/scene` and `/health`; Scene contains task information. Use the Console locally, and never forward the Hub directly to the public Internet. Bearer-enabled management APIs are a separate opt-in path; do not send a management token over untrusted plain HTTP.

## 3. Install a project-local Arduino toolchain

Use the historically verified versions below; the post-release documentation and Agent example checks do not reinstall or rebuild this toolchain:

| Tool / dependency | Version |
| --- | --- |
| Arduino CLI (Windows executable) | 1.5.1 |
| Espressif ESP32 core | 3.3.1 |
| GxEPD2 | 1.6.9 |
| ArduinoJson | 7.4.2 |
| Adafruit GFX Library | 1.12.6 |
| Adafruit BusIO | 1.17.4 |

Download the Windows archive appropriate for the PC from the [official Arduino CLI 1.5.1 release](https://github.com/arduino/arduino-cli/releases/tag/v1.5.1). Check the downloaded archive against the checksum published for that release, then extract `arduino-cli.exe` to this project's `.build/toolchain/`. The [official CLI installation reference](https://arduino.github.io/arduino-cli/latest/installation/) provides download guidance. Do not replace a global Arduino installation.

From the source root, create the directory if needed, then place the executable there:

```powershell
New-Item -ItemType Directory -Force .build/toolchain | Out-Null
```

Use the following dedicated configuration; it keeps package data, downloads and libraries within this project. If the configuration already exists, inspect it first; the example is for a new toolchain directory.

```powershell
$toolRoot = (Resolve-Path .build/toolchain).Path.Replace('\','/')
@"
directories:
  data: $toolRoot/data
  downloads: $toolRoot/downloads
  user: $toolRoot/user
board_manager:
  additional_urls:
    - https://espressif.github.io/arduino-esp32/package_esp32_index.json
"@ | Set-Content -Encoding utf8 .build/toolchain/arduino-cli.yaml
$cli = '.\.build\toolchain\arduino-cli.exe'
$cfg = '.\.build\toolchain\arduino-cli.yaml'
& $cli --config-file $cfg version
& $cli --config-file $cfg core update-index
& $cli --config-file $cfg core install esp32:esp32@3.3.1
& $cli --config-file $cfg lib install "GxEPD2@1.6.9" "ArduinoJson@7.4.2" "Adafruit GFX Library@1.12.6" "Adafruit BusIO@1.17.4"
& $cli --config-file $cfg core list
& $cli --config-file $cfg lib list
```

Confirm the CLI, core and four library versions match the table. Stop at a failed command; do not continue to compilation with missing/mismatched dependencies or silently substitute a different board core. Keep this PowerShell session open so `$cli` and `$cfg` remain defined; in a new session, set those same two variables again from the source root.

## 4. Private test configuration and compilation

Copy the supplied header once in the fresh installation:

```powershell
Copy-Item firmware/esp32_dashboard/private_config.example.h firmware/esp32_dashboard/private_config.h
```

Edit **only the local `private_config.h`**:

- `DASHBOARD_WIFI_SSID` and `DASHBOARD_WIFI_PASSWORD`: credentials for your own 2.4 GHz test network.
- `DASHBOARD_HUB_URL`: `http://` followed by the PC's confirmed private IPv4 and selected Hub port. It must match `device_host` and `port` in the Hub configuration.
- Leave optional outbound settings empty for the basic local path. No API key or model subscription is required.

Never commit, upload, paste into a report or share that private header or any firmware built with private settings. The resulting binaries can contain Wi-Fi credentials. Source-only distribution does not make your locally compiled binary safe to publish.

To compile without uploading:

```powershell
powershell -NoProfile -File .\compile_firmware.ps1 -ArduinoCli $cli -ConfigFile $cfg
```

The script passes `--fqbn esp32:esp32:esp32` and places outputs in `.build/firmware`. It does **not** upload, erase NVS, or open a serial port. Check its exit status and reported Flash/RAM usage. The build uses the classic ESP32 default board configuration; do not assume that proves compatibility with a device's currently installed partition layout. Before any later upload, record the source manifest and local build hashes:

```powershell
Get-FileHash -Algorithm SHA256 .\SOURCE_MANIFEST.json
Get-ChildItem -LiteralPath .build/firmware -Filter *.bin | Get-FileHash -Algorithm SHA256
```

These commands record identity, not hardware acceptance or a rollback backup. Keep the artifacts private and use the same approved build for subsequent device checks. No firmware build is implied by the post-release documentation and Agent example checks.

## 5. Upload and serial observation — future, separately approved operation

Select compatible test hardware and have its owner approve the exact target and operation. Before writing, confirm its identity, Flash capacity, current/target partition layouts, active application, firmware identity, Flash encryption and secure-boot constraints, and the intended write range. Where data already exists, require a verified full application-and-necessary-data backup/rollback plan; restoring only the application does not restore NVS or credentials. Unknown critical conditions mean **No-Go**, not permission to force a write. This guide is not a full backup/recovery procedure.

Ensure any supervisor or other software that might reset/reflash/control that device cannot interfere under a separately approved isolation plan. Close only a serial monitor you own for the target before upload; do not stop unrelated services or blindly select the first COM port. Use Windows Device Manager together with Arduino's listing to identify the approved test board. The serial commands themselves access the device and belong to that later approved stage.

After all gates above are satisfied, reconnect only the approved test board as needed and use the same `$cli`/`$cfg` from section 3:

```powershell
& $cli --config-file $cfg board list
$port = 'COMx'  # Replace with the owner-confirmed test-board port.
if ($port -eq 'COMx') { throw 'Confirm and set the test-board COM port before uploading.' }
& $cli --config-file $cfg upload --port $port --fqbn esp32:esp32:esp32 --input-dir .build/firmware firmware/esp32_dashboard
```

Upload writes Flash and normally resets the ESP32. It is not an NVS erase or restoration procedure, and it does not guarantee that existing data is preserved. Do not add erase/force options to get past an error. If the board cannot enter its bootloader, stop and consult its exact board instructions; any BOOT/EN or USB action is a separate deliberate physical action on the confirmed test board, not a reason to reset another device.

Only after a successful upload, observe the approved board at the source-defined baud rate:

```powershell
& $cli --config-file $cfg monitor --port $port --config baudrate=115200
```

Serial tools can affect reset/control signals on some boards; this is not a read-only operation on the currently running original board. Use the monitor's displayed exit command to close it before another upload. Store only necessary, redacted timing/error/identity evidence, never full credential or private-task logs. `H/W/I/R/?` are development display commands, not physical ACK buttons; basic acknowledgement is through the Web Console.

## 6. What final hardware acceptance must still demonstrate

Use only the approved board, isolated Hub, test network and synthetic tasks. Record the source/build hashes and target board, panel, adapter and power details. The minimum core checks are:

1. Observe the real display's Home layout, black/white/red output and task updates. For Chinese-title coverage, use synthetic titles and a legally available usable Windows font; do not bundle Microsoft fonts.
2. Observe Workspace after appropriate work context and Interrupt for an authorized synthetic reminder. Click Web ACK; verify the alert clears and the Todo remains pending.
3. Disconnect only the test network or stop only the isolated test Hub, then observe fallback after approximately 90 seconds. Restore it and observe Hub takeover after approximately 45 stable seconds. Account for polling and e-paper refresh time rather than treating HTTP 200 as display completion.
4. Record failures honestly. The private device's historical fallback/recovery observation is not a final-candidate pass. Current firmware identity on that private board is unknown.

Chinese titles can fall back to ASCII short IDs after an offline cold boot; historical NVS writes have also failed. This is an unresolved limitation, not a claim of lossless recovery. Original-board NVS diagnosis stays frozen. Offline cold-boot/NVS investigation is not an additional prerequisite to these four core checks; do not expand it into repeated flashing or a cache redesign. Exact-candidate core hardware acceptance and a safe authorized hardware photo remain outstanding follow-up work. The owner approved this source release without requiring either first; neither is represented as complete. Precompiled binaries remain unavailable.

## 7. Troubleshooting without destructive shortcuts

| Symptom | Check / action |
| --- | --- |
| `py -3.13` missing or dependency import fails | Check `py -0p`, the local `.venv` interpreter, locked requirements and `pip check`; do not mix another project's environment. |
| CLI/library/core missing or wrong version | Check executable location, project `$cfg`, `version`, `core list` and `lib list`; stop on a failed install rather than replacing source files from a private build. |
| Missing `private_config.h` | Copy the example only in the new local installation, then enter your own test settings. Do not copy someone else's private header. |
| Compile too large or upload layout/security mismatch | Keep the failure evidence; verify the exact target and default partition assumptions. Do not change partitions, erase data or bypass protection under this guide. |
| Upload port busy or board absent | Reconfirm the actual board/COM mapping and data-capable cable. Close your own target monitor only. Do not kill unknown processes. |
| Wi-Fi connects but Hub cannot be reached | Check 2.4 GHz network, actual PC IPv4, `device_host`, URL/port, Private firewall and access-point isolation. Do not expose the server publicly. |
| Local Console works but LAN management returns 401 | Use the browser on the Hub PC. Anonymous LAN is intentionally limited to Scene/health; do not disable authentication. |
| `/health` works but `/scene` times out | Record real business endpoint latency and redacted `slow-diagnostics.jsonl` stages in the new Hub data directory. Injected long transactions can exceed the device's 5-second timeout; do not increase it to claim a fix. |
| Chinese missing while ASCII works | Check the startup font warning and a usable legally installed Microsoft YaHei. Restart only your isolated Hub after resolving the font. Font files are not included in this release. |
| Offline cold boot shows short task IDs | Record version/connectivity and whether the screen actively refreshed. Keep the known limitation; do not erase NVS or repeatedly flash the original board. |
| Weather/NTP/Radar remains UNKNOWN | Base local tasks do not need them. Device acquisition requires a successful configured Internet Probe and further source-specific conditions below. |
| A reminder remains or refresh seems delayed | Observe the Console ACK result, next Scene poll (roughly 30 seconds) and actual panel refresh. ACK does not complete a Todo; a manual context does not force every page. |

Optional device NTP/weather/Radar is experimental. `DASHBOARD_INTERNET_CHECK_URL`, `DASHBOARD_INTERNET_CHECK_STATUS` and `DASHBOARD_INTERNET_CHECK_LOCATION` must match a stable credential-free endpoint's status and Location header (empty if absent). An empty probe URL keeps Internet UNKNOWN and prevents new device NTP/weather/Radar acquisition even with working local Scene. NTP also requires a timezone and both NTP servers; weather requires coordinates and a valid local date and runs only in Standalone/Hub Home; native device Radar needs its URL and a valid date and runs only in Standalone. Probe success is only a prerequisite, not proof of those services. Hub-side Radar is a separate path. Leave all optional services unconfigured for the core test if not needed.

Software validation remains limited; exact public firmware hardware acceptance is incomplete. Two legacy JSON migration failures are retained. See [current validation](VALIDATION.md), [CI scope](CI.md) and [Agent HTTP quickstart](AGENTS.md#agent-http-quickstart).
