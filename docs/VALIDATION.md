> 当前发布状态（2026-10-20）：offline-final2 已通过独立软件复审，所有者批准源码发布。精确公开固件真机验收和真实硬件照片仍待补；下文为历史验证记录，不把旧发布门槛或历史设备成功当作当前候选验收。平台结果见 [Actions](https://github.com/Tkkdy/attention-router/actions)。

# 验证记录与候选身份

## M1.1-releaseprep1 发布准备（2026-10-18）

本候选基于 M1.1-stability1（父 ZIP SHA256 `95bb54e14f65a4721c2ae8eba616045012390b534221479babcb042f95fd9759`），本轮仅整理许可、版权、文档与发布材料，不开发新功能，不合并原板 NVS 诊断补丁。具体文件身份以本候选 manifest 与最终文件清单为准。

| 对象 | 已有证据 | 不得外推的结论 |
| --- | --- | --- |
| M1.1-stability1 基础软件 | 定向 9/9；核心 86/88，保留两项旧迁移失败；三接口并发时延见下文 | 不等于真实 Wi-Fi、NVS 或实屏通过 |
| 私人运行版本 | 真机观察到 Hub 失联降级、稳定窗口自动恢复；离线冷启动显示 ASCII 占位标题，联网后原任务名称恢复 | 当前固件精确身份 UNKNOWN，不能算作公开候选验收；不能证明 NVS 问题已修复 |
| M1.1-stability1 / M1.1-releaseprep1 精确候选 | 复用未受影响的构建与软件证据；尚无最终精确二进制真机闭环 | 不声称最终固件完整硬件验收、中文离线恢复或高级集成端到端通过 |
| 原板 NVS 诊断 | 风险评估完成，原板刷写 No-Go，诊断冻结 | 不把未定位根因扩展为持续开发或所有发布准备的默认阻断 |

本轮核对 README/安装命令与源码调用入口、配置隔离、构建参数、缓存条件和历史测试结果，未启动 Hub、打开串口、刷写设备或改动真实任务。对应代码行为未改变的测试复用下述历史证据，不能把它们标作本轮新运行。后续备用板基础验收参见 [HARDWARE](HARDWARE.md)；私人离线标题问题另见 [LIMITATIONS](LIMITATIONS.md)。正式公开仍由所有者批准。

## M1.1 有限验证（历史证据）

2026-10-17；Windows / Python 3.13.7。仅新候选及本轮临时目录，无真实模型、Bot、生产数据或实物操作。

| 验证层级 | 结果 | 边界 |
| --- | --- | --- |
| 输入身份 | PASS | 原 M1 ZIP SHA256 匹配，145 文件与现有 source 逐字节一致；交付时再次核对不变 |
| 新装依赖 | PASS | 全新 venv，从 PyPI 使用 requirements.lock.txt 安装；pip check 成功，不依赖原 .build |
| Hub 软件回归 | 86/88 PASS | 剩余 1 failure + 1 error 均为两项旧 JSON 迁移问题；无跳过、未删断言 |
| R1/R2/R5 定向用例 | 3/3 PASS | 默认/启用来源状态，字体存在/缺失 × 英文/中文，真实设备 capabilities，LAN 匿名/Bearer；TestClient 合成数据 |
| C++ 主机模拟 | 7/7 PASS | 可选来源禁用/启用两组，缓存、故障恢复、authority，真实 ArduinoJson 与 json-c 替身两组解析；fake HTTP/NVS，非 ESP32 |
| Console 合约 | PASS | 实际 Console 脚本 + mock DOM |
| Hub 启动/演示/ACK | PASS | 未占用 loopback 端口，monitor=false，新数据；实际无头 Chrome 点击 ACK，Todo 不变，Current 引用 Todo ID，Next 不重复 |
| 官方固件构建 | PASS | Arduino CLI 1.5.1，官方 ESP32 Core 3.3.1，GxEPD2 1.6.9，ArduinoJson 7.4.2，Adafruit GFX 1.12.6 / BusIO 1.17.4；FQBN esp32:esp32:esp32 |
| 配置与编译输入 | PASS | 从公开模板生成合成有效配置，仅编译副本含 private_config.h；公开固件文件与构建输入逐字节相同 |
| 真机 / NVS / 实屏 | NOT TESTED | 未刷写/重启 ESP32；历史 Scene cache write failed 风险仍在，按 HARDWARE 人工验收 |
| 真实 Bot / 模型 / OAuth / Tunnel | NOT TESTED | 未付费调用、未访问私人账号；实验能力不扩展 |
| Git / manifest / ZIP | 交付脚本逐项核对 | 普通 git add 后的 ls-files、blob、source、manifest 和 ZIP 必须一致；无旧 Git 历史 |

构建输出：

```text
Sketch uses 1231023 bytes (93%) of program storage space. Maximum is 1310720 bytes.
Global variables use 101780 bytes (31%) of dynamic memory, leaving 225900 bytes for local variables. Maximum is 327680 bytes.
```

## 保留的失败

- test_atomic_migration_keeps_json_and_restarts：IndexError。
- test_invalid_migration_is_atomic：预期 ValueError 未触发。

它们针对旧 JSON 导入/初始化时机；本轮支持空目录新装，禁止把新装通过扩大成旧数据迁移通过。测试失败保留，未重构生产迁移。

R1 改变了默认可选来源的语义，旧测试中两处 assertTrue(stale) 改为 assertFalse，保留其他 UNKNOWN/设备回执断言，并新增已启用失败仍 STALE 的断言。原诊断脚本故意断言错误行为，只在原包副本运行确认，未要求修复后继续通过。

中间失败也保留：新增测试误用方法名、备用 json-c 生成头未部署完整、CMake 兼容策略、浏览器 ACK 定位歧义；分别纠正测试/临时环境后完成复验，没有因此放宽固件校验。首次工具链下载主动停止后使用官方哈希核验缓存继续安装，未复用已安装的定制 Core。

未受影响的 DeepSeek 模拟合约、显示/Radar 主机合约复用 M1/交接已有证据，本轮不重复扩展全套或真实外部服务验收。并不声称 run_host_checks.py 全绿。

原始命令、退出码、环境、完整输出、截图及构建来源证据位于候选旁 validation/；该目录不随公开源码 ZIP。最终候选设备验收尚未完成；许可与署名已在 M1.1-releaseprep1 获所有者确认，详见 LICENSING。


## M1.1-stability1 定向修订（2026-10-17）

基于最终 M1.1-docs1 ZIP（SHA256 a806f8adfb45ddd3b5422836cee9f44e6f8f4ffbccc0988a430bd3ee534d22c5）选择性修订。
完整上下文采样、默认 Tibo preferences 检查及 Radar 刷新进入工作线程；取消时等待当前工作完成，采样串行门和配置锁防止重叠。overview 复用只读快照，显式请求审计保留。SQLite 连接仍线程局部，Scene、delivery 和正式快照仍在同一事务发布。

新增 `hub/test_preview_stability.py`：9/9 PASS。运行命令（已安装锁定依赖，工作目录 hub）：

```powershell
python -B test_preview_stability.py -v --results <候选外的证据路径.json>
python -B -m unittest -v test_hub test_attention test_m2 test_m3 test_scene_snapshot test_context_v2 test_monitor test_radar_client test_tibo test_butler_todo_projection test_preview_revision
```

测试使用 Windows / Python 3.13.7、原 M1.1 锁定依赖环境、临时数据库、合成前台样本与任务、随机 loopback 端口、真实 Uvicorn HTTP。默认监控开启；不调用真实前台采样或任何外部集成。

| 场景 | /health 最大耗时 | /scene 最大耗时 | /api/overview 最大耗时 |
| --- | --- | --- | --- |
| 事务外采样延迟 6 秒（各 4 请求） | 15.7 ms | 53.3 ms | 45.9 ms |
| 20 次采样与 20 次合成写入并发（各 20 请求） | 12.9 ms | 50.0 ms | 35.6 ms |

故障注入持锁 6 秒：41 次 health 最大 5.9 ms；5 秒客户端的 scene/overview 均 READ_TIMEOUT；10 秒客户端分别约 6.043/6.028 秒返回 200。此项证明等待可诊断，不代表故障下业务不超时。分阶段日志正确区分 Python 锁等待与 SQLite BEGIN 等待；事务体和 commit 独立计时。

核心回归 86/88 PASS；仍为上文同名两项旧 JSON 迁移失败，无新增失败。取消重复调用、配置更新竞态、采样/存储异常、回滚、只读 observation、审计及正式快照不变、诊断脱敏和轮转均有针对性检查。公开版 STALE、字体降级、数据目录隔离修订保留。

诊断位于本候选 data_dir 的 slow-diagnostics.jsonl，默认阈值 1000 ms，256 KiB × 最多 3 文件。仅白名单接口、生成的关联 ID、状态和耗时；不记录请求参数、个人任务、窗口标题、Token 或异常内容。数据库阶段仅针对 RouterStore 外层事务/observation 边界，未声称覆盖所有第三方调用或其他外部锁。请求耗时是服务端处理至响应头就绪；HTTP 验收耗时由客户端独立测量。

边界：真实 Windows 前台采样、Wi-Fi、ESP32、NVS/屏幕、私人高级集成未在本轮复验。线程取消需等待当前同步调用结束，不能强制终止挂起的线程；长事务/大量排队仍可能超过 5 秒。本轮不改 SQLite journal mode、schema、固件或客户端超时。该次稳定性修订未改变旧迁移或发布关卡，许可在后续 M1.1-releaseprep1 单独落实。固件源码在 stability1 修订中未变，沿用先前构建证据，未重新刷写或发布。


## M1.1-releaseprep1 离线收尾核验（2026-10-18）

本轮只增加许可注释和发布文档，没有功能修改。126 个代码文件移除新增的 SPDX/版权注释后与 M1.1-stability1 ZIP 逐字节一致；64 个 Python 文件 AST 一致。公共证书、上游补丁及原 LICENSE/NOTICE 等五项逐字节保留。9 个 JavaScript 文件语法、5 个 PowerShell 文件解析、Console mock DOM 合约通过；文档本地链接与围栏检查通过。

这些结果只验证本轮许可/文档变动。没有重新启动服务、安装依赖、重跑全套、编译或刷写设备；M1.1-stability1 的 9/9、86/88 和固件历史构建证据依其适用范围复用。精确新候选二进制真机验收仍未完成。

公开树的最终文件集合由 GIT_FILES.txt、LICENSE_MAP.json、SOURCE_MANIFEST.json 和交付 ZIP 逐项核对。原始命令/返回码、脱敏隐私扫描及字节差异保存在所有者的独立交付证据目录，不随公开源码包。没有初始化 Git、继承私人提交或创建远程仓库；未来首次提交还须按 PUBLISHING.md 检查，不宣称私人历史已经审净。


## v0.1.0 offline-final1（2026-10-19）

本轮以已核验的 M1.1-releaseprep1 源码 ZIP 为基线（SHA-256 `c01b0ef51762189b1a64e5c30d0c47d4ccf3291cae8ab475417626ba2a0de959`）。只修改文档、文件清单、发布材料并添加 CI、社区模板和真实合成数据截图。现有业务代码、测试、固件、配置模板、依赖锁和第三方许可均逐字节核对；正式结果以外部审查包中的差异和证据为准。

- 当前本地轻量 CI：`python -B ci/check_source.py`；`python -B ci/run_basic.py`；`node hub/test_console_runtime.cjs`。19 项选定基础回归通过，Console mock 合约通过。选定集明确不包括上文两项旧迁移失败，没有修改或删除旧测试；不是全套通过。
- Python 3.13.7 / Node 24.19.0；复用已安装环境，18 项锁定依赖版本一致。本轮没有重新下载依赖。GitHub Actions **NOT RUN**，workflow 仅本地静态检查与命令验证。
- 新截图使用实际候选 Console、独立临时数据库、合成任务、UTC 浏览器时区及临时 loopback HTTP 端口。真实浏览器点击 ACK 后待办未改变、页面无错误；截图不代表 ESP32 在线或硬件通过。临时服务已经停止。
- 初次隔离 CI 驱动错误地阻断 Windows asyncio 的标准库 socketpair；修复驱动中的精确标准库例外后 19/19 通过，没有放宽应用测试断言。原始失败输出保留在私有审查证据中。
- 截图导入模块产生的默认临时数据库已移至私有审查临时目录，公开树不含该产物。CI 在临时 Hub 副本执行以避免同类污染。
- 固件字节未变，复用上文历史构建及容量数据，不重新编译、不操作串口或实板。最终精确候选核心真机验收、真实高级集成、长期可靠性均未在本轮验证。
- 最终候选使用 `.gitattributes` 保留文件原始字节，避免未来 Git 的换行转换破坏已审查哈希；不改变全局 Git 配置。本轮没有创建 Git 仓库或提交。

离线材料完成仅表示可交独立复审。正式公开仍须独立复审、安全有限的最终候选核心真机验收和所有者单独授权，详见 [PUBLISHING](PUBLISHING.md)。
