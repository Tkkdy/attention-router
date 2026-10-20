<!-- SPDX-FileCopyrightText: 2026 Tkkdy -->
<!-- SPDX-License-Identifier: MIT -->

# Contributing

[中文](CONTRIBUTING.md) · [Project overview](README_EN.md)

Issues are welcome for bug reports and suggestions, and Pull Requests for focused improvements. Discussions are not planned for launch. The public repository is `Tkkdy/attention-router`.

## Start with a reproducible problem

Check the [known limitations](docs/LIMITATIONS.md), [validation record](docs/VALIDATION.md), and existing issues. Include your version or source hash, environment, minimal reproduction, and expected and actual results. Distinguish software tests, observations on a historical private build, and hardware results for the final public candidate.

The launch target is a classic ESP32 with 4 MB Flash, a GDEY042Z98 400×300 black/white/red display, and a verified matching SPI adapter. Confirm the actual board, power supply, and wiring against the [English hardware guide](docs/INSTALL_EN.md). Seeed XIAO ESP32S3 is outside the launch support scope. Safe, limited hardware acceptance of the final candidate remains incomplete; private-device history and simulations do not substitute for it.

Chinese task titles may fall back to short ASCII identifiers after an offline cold boot. This is a known limitation, and full NVS root-cause diagnosis is frozen. Report connectivity, whether this was a cold boot, and whether the screen actively refreshed. Do not erase NVS, repeatedly flash devices, or expand diagnostics just to file a report. Device writes require the hardware owner’s approval.

## Protect data and devices

- Reproduce with a temporary database, synthetic tasks, and an isolated port. Do not perform destructive tests on real tasks, private services, or an in-use device.
- Do not submit real task or window titles, complete private screen contents, accounts, private domains, Wi-Fi configuration, tokens, API keys, cookies, private keys, databases, or raw NVS/Flash backups. Redact screenshots and logs; retain only necessary error codes, stages, and timings.
- Hardware changes and flashing require the device owner's explicit approval. An issue or PR is not permission to operate a device. State what remains untested when a safe reproduction is unavailable.

## Keep pull requests focused

1. Work in an isolated directory and address one concrete problem per PR. Discuss changes to behavior, architecture, or hardware scope in an issue first.
2. Follow the [English installation guide](docs/INSTALL_EN.md). Run checks relevant to your change that your environment supports, and record commands, result summaries, and reasons for untested areas. Contributors do not need hardware, paid models, or private integration accounts.
3. Preserve the two known legacy JSON migration failures and report their actual results. Do not delete tests, weaken assertions, or hide failures to claim a fully passing suite. See the validation record for the cases. Passing lightweight CI proves only its listed checks, not hardware acceptance or complete migration support.
4. Describe the problem, change, validation, and remaining risks. Keep Chinese and English documentation aligned when documented behavior changes. Avoid unrelated formatting and broad refactors.

## Licensing and provenance

Independent original Hub, Web Console, tools, and this guide use MIT. Original firmware uses GPL-3.0-only. Third-party material retains its own terms. Read the [component licensing guide](docs/LICENSING.md) and [third-party notices](THIRD_PARTY_NOTICES.md). Do not replace this with a repository-wide MIT grant or silently change SPDX identifiers, copyright notices, or upstream notices.

Submit only code, images, and documentation you have the right to contribute, and offer original contributions under the existing license of the target component. Identify the source, author, and license of new third-party material. Do not label material of unknown origin as your own. Preserve contributors' real attribution rather than replacing all names with Tkkdy. No new CLA or DCO signing process is required.
