# Attention Router

[中文](README.md) | **English**

**Keep tasks, work context and important alerts in view on your desk.**

A local-first desktop attention router. A Windows Hub stores tasks, work context and alerts; Agents connect through authenticated HTTP; the Web Console provides inspection and acknowledgment; an ESP32 e-paper display polls the resulting Scene. Console-only use needs no hardware or model subscription. Routing is deterministic, without LLM calls.

![Real ESP32, adapter and e-paper desktop prototype showing Home](assets/hardware-overview.jpg)

*The physical prototype: ESP32, adapter and 4.2-inch e-paper. Home keeps a small ordered task list visible; the full list stays in the Hub.*

[Quickstart](#windows-quickstart) · [Hardware](docs/HARDWARE.md) · [Agent integration](docs/AGENTS.md) · [Features and plans](docs/FEATURES.md)

## See it in use

- **Home:** Keep the first three pending tasks in view.
- **Workspace:** See Current and Next while you work.
- **Interrupt:** Surface an alert for manual acknowledgment in Hub Web. ACK never completes the task.

<table>
<tr><th>Workspace · Current and Next</th><th>Interrupt · Manual acknowledgment</th></tr>
<tr><td><img src="assets/device-workspace.jpg" alt="Physical Workspace page with SIMULATED and STALE labels retained" width="460"></td><td><img src="assets/device-interrupt.jpg" alt="Physical Interrupt page with an ASCII message and ACK IN HUB WEB" width="460"></td></tr>
</table>

These owner-supplied photographs show real hardware. Visible `SIMULATED` / `STALE` labels describe demo or freshness state; the photos do not prove live data, forecast accuracy or acceptance of the exact public firmware. The Workspace photo retains prototype text overlap; Interrupt shows ASCII text. See the limits below.

<details>
<summary>Web Console: inspect and acknowledge on your computer</summary>

![Real Console with synthetic data](assets/console-demo.png)

Rendered by a real browser against an isolated Hub using synthetic data. It does not prove a connected device or completed display. [Asset provenance](assets/ASSET_INDEX.md).

</details>

## Core capabilities

| Capability | Behavior |
| --- | --- |
| Home / Workspace | Ordered Todo, Current, Next; Windows work signals and manual overrides |
| Interrupt | Authorized NOW / QUEUE / DIGEST / DROP routing; manual ACK never completes Todo |
| Console / Agent HTTP | Inspect provenance, Scene and freshness; revision conflicts and idempotent writes |
| Tibo (experimental) | Community Reset/forecast, 60-second manual detail, opt-in threshold page |
| Autonomous AI Interrupt (experimental) | Explicit standing owner permission lets AI choose timing/text; existing Router and manual ACK remain |

Home's TODAY means the first three pending Todos, not a date filter. DIGEST classifies/stores information; automatic summaries are unimplemented. show_interrupt reuses Interrupt; there is no separate Interact page.

## Windows quickstart

Open PowerShell in a fresh checkout with Python 3.13 installed:

~~~powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Copy-Item config.example.json config.local.json
.\.venv\Scripts\python.exe hub\run_preview.py --api-token-prompt
~~~

Privately enter your own random 32+ ASCII character token without whitespace. Open <http://127.0.0.1:8765/>. Default listener is loopback only; data stays in .build/preview-data/. Ctrl+C stops it; re-enter the token after restart. Use fresh data only.

In another terminal run the model-free example and enter the same token:

~~~powershell
.\.venv\Scripts\python.exe examples\agent_http_demo.py
~~~

It creates a synthetic Todo, links Current by its returned ID, publishes an authorized reminder and verifies that ACK leaves Todo pending. Retries preserve exact requests; a 409 reads revisions and stops without overwriting. [Agent HTTP guide](docs/AGENTS.md#agent-http-quickstart) · [English installation](docs/INSTALL_EN.md).

## Tibo and AI Interrupt

**Tibo:** Enable collection and forecast in the Console, save, then enable the automatic Reset page. Only a fresh **24-hour probability strictly above the threshold (70% by default)** initially triggers it. Once triggered it stays until manually switched off, even if probability drops; expired data is STALE. Switching off clears the latch and manual detail and restores normal routing. Active reminders retain priority; re-enabling can trigger again. Manual detail remains 60 seconds by default. Devices need tibo-v1. Community forecasts guarantee neither resets nor personal quota.

**AI:** The independent Gateway requires --allow-autonomous-interrupts and privately entered Hub and distinct provider-bound Gateway tokens. show_interrupt accepts printable English ASCII title/message, each 1–47 characters. AGENT provenance distinguishes AI origin from the owner's standing interruption grant. Permission is closed by default. [Enable, call, retry and disable](docs/AGENTS.md#autonomous-interrupt).

GrokBot, DeepSeekBot, MCP/OAuth, Todo Core projection, Codex quota, Radar and weather are optional experiments. DeepSeekBot adapters are included; complete independent chat-web installation remains unaccepted. Basic HTTP is independent. [Integration boundaries and optional Interrupt MCP facade](docs/AGENTS.md) · [Features](docs/FEATURES.md). General Agent lifecycle, execution-completion detection and physical ACK buttons are unimplemented.

<details>
<summary>Tibo on hardware: community Reset status and experimental forecasts</summary>

<img src="assets/device-tibo.jpg" alt="Physical Tibo Reset Watch page retaining the SIMULATED label" width="680">

A photographed Tibo page with community sources and experimental forecasts. Dates, probabilities and the `SIMULATED` label are preserved; this is not a current reset announcement or a personal quota guarantee.

</details>

## Hardware, security and limits

- Target: classic ESP32 (4 MB Flash) + **GDEY042Z98 4.2-inch 400×300 black/white/red SSD1683** with matching adapter. Other same-size panels are not interchangeable; ESP32S3 is unsupported. [Wiring/voltage/build](docs/HARDWARE.md).
- Source only, no precompiled firmware. Exact public firmware display, NVS/power-loss recovery and complete hardware acceptance remain untested. Some Chinese titles require a legally installed font; offline titles may fall back to ASCII.
- Trusted LAN only. Never expose Hub/Gateway/databases directly. Bearer access is broad; HTTP does not protect tokens. Anonymous Scene reads can contain task data. [Network](docs/NETWORK.md).
- A prepared Scene response does not prove device display: delivery is UNKNOWN. Default polling is about 30 seconds; this is not an emergency alert system.
- Fresh data directories only; two legacy JSON migration failures remain. Existing STALE, worker/cancellation and cache fixes are retained. [Limits](docs/LIMITATIONS.md) · [Validation](docs/VALIDATION.md) · [CI](docs/CI.md).

Existing v0.1.0 Tag/Release remains; main may include subsequent maintenance. Verify hardware and complete backups before device writes. Builds may embed Wi-Fi credentials; never commit private configuration, databases, logs or personal firmware.

## From desktop prototype to attention assistant

![Grok Bot concept showing multi-source task organization and a desktop display](assets/grok-bot-concept.png)

**Concept illustration, not a current product screenshot.** This owner-supplied Grok Bot demo illustrates “describe a task → organize it → keep it visible.” Automatic integration of email, calendars, team messages, knowledge bases and browsers is a vision, not a claim of shipped connectors or complete workflows. Available and experimental paths are described above and in [Features](docs/FEATURES.md). Third-party marks do not imply affiliation.

## Contribution and licensing

[Contributing](CONTRIBUTING_EN.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [License scope](docs/LICENSING.md)

Copyright © 2026 Tkkdy. Original independent Hub, Console and tools: **MIT**. Original ESP32 firmware: **GPL-3.0-only**. Third-party terms remain applicable. Both permit commercial use; root MIT does not override firmware GPL.
