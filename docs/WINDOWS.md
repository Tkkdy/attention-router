# Windows 安装与启动

支持 Windows 桌面 / Python 3.13；已有软件验证版本为 3.13.7。v0.1.0 发布源码；精确公开固件真机验收尚未完成。`run_preview.py` 是保留的实际入口名，不表示发布时使用 GitHub Pre-release。

## 新目录安装、启动与停止

在全新解压目录用 PowerShell 执行，不依赖作者 `.build`：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip check
Copy-Item config.example.json config.local.json
.\.venv\Scripts\python.exe hub\run_preview.py
```

浏览器打开 <http://127.0.0.1:8765/>；默认仅本机监听。Console 会建立本机浏览器会话，无需在 URL 输入凭据。只在这个 Hub 的终端按 `Ctrl+C` 退出；同一命令再次启动会复用本候选数据，不自动清库。安装不配置开机启动或系统服务。
`requirements.txt` 仅记录五个直接依赖用途：FastAPI 服务、Uvicorn 运行、Pillow 标题位图、tzdata 时区、httpx 客户端/测试；锁定文件包含完整应用依赖。

复制 `config.example.json` 为 `config.local.json`。`port` 默认 8765；`device_host: null` 仅本机；`monitor: true` 采集 Windows 前台信号，false 可手动操作。新数据在本目录 `.build/preview-data`；禁止直接复用私人旧数据，旧 JSON 迁移不是支持路径。

运行 `.\.venv\Scripts\python.exe hub\run_preview.py`，Ctrl+C 退出。端口占用时修改本地配置和固件 Hub URL，不终止其他应用。非默认端口给演示加 `--url http://127.0.0.1:端口`。演示添加 Todo/提醒并引用该 Todo 作为 Current，不清空其他事项；仅在新安装中使用。

## 合成任务与提醒演示

保持自己的新 Hub 运行，另开同目录 PowerShell：

```powershell
.\.venv\Scripts\python.exe examples\local_demo.py
```

示例新增一个英文 Todo，将同一 ID 作为 Current，并添加明确授权的提醒；多次执行会新增示例，不是幂等清场工具。Console 点击 ACK 后，提醒退出，Todo 应仍未完成。需要 Workspace 时手动选择 CODING，它是上下文输入，不保证抢占已授权提醒或可选详情页。

Home 的 TODAY 仅显示已有顺序中前 3 个 pending Todo，不做“今天到期”筛选；Next 排除 Current 的 ID。当前基础演示不用模型、Bot 或设备。若检查中文，在新数据库中通过受权 API 提供合成 `display_title` 和合法 ASCII `title`，不要把生产任务搬入演示。

微软雅黑来自用户合法 Windows 安装，不随包分发。启动时检查字体；缺失/不可读取时警告并使用现有 ASCII 标题，英文设备请求仍可返回 200，中文显示名无法绘制。安装可用字体后重启 Hub。中文位图仅用于 Todo/Current，其他字段仍限制 ASCII/长度。

## 官方固件工具链（隔离示例）

目标 `esp32:esp32:esp32`，经典 ESP32 Dev Module / 默认 4 MB 分区与指定 GDEY042Z98 屏。Seeed XIAO ESP32S3 不是本版支持目标，也不能替代最终候选验收。下载 [官方 Arduino CLI](https://arduino.github.io/arduino-cli/latest/installation/) Windows 版本，将 exe 解压到本项目 `.build/toolchain`；已验证 CLI 1.5.1。不要覆盖既有全局 Arduino 配置。

在源码根目录 PowerShell 创建本项目专用配置：

```powershell
New-Item -ItemType Directory -Force .build/toolchain | Out-Null
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
& $cli --config-file $cfg core update-index
& $cli --config-file $cfg core install esp32:esp32@3.3.1
& $cli --config-file $cfg lib install "GxEPD2@1.6.9" "ArduinoJson@7.4.2" "Adafruit GFX Library@1.12.6" "Adafruit BusIO@1.17.4"
Copy-Item firmware/esp32_dashboard/private_config.example.h firmware/esp32_dashboard/private_config.h
```

只编辑本地 `private_config.h`，填自己的 2.4 GHz Wi-Fi、Hub LAN IPv4 和端口。基础本地部署可将所有可选外网项留空。

若要启用**设备端** NTP、天气或 Radar，必须同时配置 `DASHBOARD_INTERNET_CHECK_URL`、预期 HTTP 状态 `DASHBOARD_INTERNET_CHECK_STATUS` 和预期 `Location` 响应头 `DASHBOARD_INTERNET_CHECK_LOCATION`（没有该头时填空串）。使用自己选择、无需凭据且响应稳定的探测地址；不要在 URL 中放令牌或私人信息。设备会发起额外外网 GET 请求，状态码与 Location 必须都匹配；通过串口 `Internet probe HTTP:` 与 `Internet probe: ON` 确认探测成功。仅 Wi-Fi 已连接或 LAN Hub 可达不足以满足此条件。

探测 URL 留空时 Internet 保持 UNKNOWN，设备端 NTP 不启动同步，天气/Radar 不发起获取，即使其余相关配置已填。NTP 还要求时区与两个 NTP 服务器均非空；天气要求经纬度和有效本地日期，且只在 Standalone 或 Hub Home 时获取；设备原生 Radar 要求地址、有效日期且仅在 Standalone 时获取。Online 是前置条件，不保证外部源、DNS、证书或时间服务可用；可选服务仍为 Experimental。Hub 端 Radar 的配置/获取是另一条路径，见 NETWORK/AGENTS，本段不把它与设备端适配器混为一谈。

确认板卡/接线/供电后仅编译：

```powershell
powershell -NoProfile -File .\compile_firmware.ps1 -ArduinoCli $cli -ConfigFile $cfg
```

脚本只编译。`.build/firmware` 可能嵌入 Wi-Fi 凭据，禁止提交/发布；本候选不含 `.bin`。

## 备用测试板的上传模板（另行批准后执行）

以下模板只用于所有者已批准的测试设备。优先使用兼容备用板及独立测试网络，先按 [硬件确认与验收](HARDWARE.md) 核对板卡、Flash/分区与 VCC。命令会上传构建目录中的固件产物并重启，不是“仅恢复原应用”的回滚方案；不能假设应用恢复会同时恢复 NVS。已有数据的板卡必须先有经验证、覆盖应用和必要数据分区的备份及回滚方案；安全状态、分区或固件身份不明时不写入。

以下 COMx 必须改成所有者确认的备用板端口；只有在上述条件满足并得到具体批准后执行。

```powershell
& $cli --config-file $cfg board list
# 与 Windows 设备管理器交叉核对端口/板卡；上传会重启 ESP32。
& $cli --config-file $cfg upload --port COMx --fqbn esp32:esp32:esp32 --input-dir .build/firmware firmware/esp32_dashboard
& $cli --config-file $cfg monitor --port COMx --config baudrate=115200
```

设备与 Hub 必须处于可信 LAN；本地配置的 device_host 和固件 HUB URL 必须对应。不要自动开放防火墙，也不要将 Hub 直接转发到公网。

## 局域网与本地 Agent

`config.local.json` 的示例内容：

```json
{"port":8765,"device_host":null,"monitor":true}
```

`device_host: null` 表示只监听 127.0.0.1；连接设备时设为电脑当前指定私有 IPv4，固件 `DASHBOARD_HUB_URL` 使用相同 IP/端口，重新启动的只应是本人的隔离 Hub。地址只能是明确的 RFC1918 IPv4，不能用 0.0.0.0、主机名或公网地址。示例地址不代表已存在可达网卡。安装脚本不会自动添加防火墙规则；必要时仅在可信 Private 网络限制设备来源放行。

需要本地 Agent 管理 API 时使用：

```powershell
.\.venv\Scripts\python.exe hub\run_preview.py --api-token-prompt
```

在私密提示中输入调用者自建的 32+ ASCII 非空白字符 token，不写入 URL、Git 或日志。有效 Bearer 在绑定 LAN 上也有管理权限；明文 HTTP 会暴露它，建议 Agent 用本机地址。匿名设备仅可读取 Scene/health，但 Scene 含任务信息。公网 OAuth/Tunnel 另见 [NETWORK](NETWORK.md)，不属于快速安装步骤。

## 故障排查（先保留数据）

| 现象 | 最小检查与处理 |
| --- | --- |
| `py -3.13` 不存在 | 核对 Python 3.13 安装及 `py -0p`；不要改全局默认解释器来绕过版本问题。 |
| 依赖导入错误 | 确认使用本目录 `.venv\Scripts\python.exe`，重新核对锁定依赖和 `pip check`；不要混用 MCP 实验环境。 |
| 端口已占用 | 在本地配置选择未使用端口，demo 和固件 URL 同步修改；不要终止未知进程。 |
| `unknown configuration fields` | 基础 JSON 只接受 port/device_host/monitor；Codex executable 等高级集成字段不是此入口配置项。 |
| Hub 本机可访问但设备不通 | 核对 Wi-Fi/LAN、电脑实际网卡 IP、device_host、固件 URL 端口、Private 防火墙与接入点隔离；不要把服务改绑公网来测试。 |
| LAN Console/API 返回 401 | 匿名 LAN 不提供 Console 管理会话；用本机浏览器，或在可信路径使用自己启用的正确 Bearer。不要放宽鉴权。 |
| 页面仍在 Home / 提醒覆盖工作页 | AUTO 有会话阈值；手动上下文不直接强制页面，检查 NOW 事件及可选详情页。前台应用信号不是 Agent 执行状态。 |
| Today 不只显示今天的事项 | 这是当前实现：按既有顺序取 pending，而非日期过滤。 |
| 任务中文缺失但英文正常 | 检查字体警告和合法本机微软雅黑；只支持部分标题位图。恢复可用字体后重启自己的 Hub；不要分发 Windows 字体文件。 |
| 离线冷启动变成短编号 | 已知 NVS/Last Scene 中文恢复限制；保留现象和版本信息，不擦 NVS、不反复刷写设备。联网标题恢复也不证明离线缓存无损。 |
| 天气/NTP/Radar 一直 UNKNOWN | 检查是否主动配置所有前置项和 Internet Probe 状态；本地 Scene 可用不表示外网探测成功。基础模式可保持这些来源未配置。 |
| `/health` 正常但 `/scene` 超时 | 记录业务接口耗时及本候选 data_dir 内 slow-diagnostics.jsonl 的脱敏阶段，不把 health 当作业务验收。长事务故障下仍可能超过设备 5 秒。不要通过增大固件超时掩盖问题。 |
| 构建找不到头文件 | 检查项目专用 `$cfg`、固定库版本和本地 private_config.h；不要复制私人构建目录覆盖源码。 |
| 全套测试报旧 JSON 迁移失败 | 已知 `test_atomic_migration_keeps_json_and_restarts` 与 `test_invalid_migration_is_atomic` 未通过；保留失败，不删断言，不直接导入旧数据库。 |

本地 slow diagnostics 默认超过 1000 ms 记录，单文件约 256 KiB、最多 3 文件；含白名单接口、关联 ID、Python 锁/SQLite BEGIN/事务体/commit 等阶段。仅表示已覆盖的边界，不是所有外部阻塞的根因证明。分享问题时不要提交数据库、窗口标题、请求正文、真实任务、Token、Wi-Fi、私有域名或完整未审查日志。

## 有限开发验证

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s hub -p test_preview_revision.py -v
node hub/test_console_runtime.cjs
```

C++ 主机测试需要 g++17。优先将 `ARDUINOJSON_SRC` 指向自行安装的 ArduinoJson 7.4.2/src；备用 `tests/parser_fakes` 路径还需要 json-c 开发头/库（本轮 0.18）。`run_host_checks.py` 是历史全套入口：已知迁移失败会使 Python 阶段退出，扩展 MCP 还需实验依赖；不能宣称此入口全绿。各轮证据按来源分开保存：M1.1 的 `validation/commands.jsonl`，M1.1-stability1 的 `evidence/commands.jsonl`。它们是对应候选旁的私有验收资料，不随公开源码 ZIP 发布。可复制执行的命令和已知失败摘要见 [验证记录](VALIDATION.md)；不能将本轮文档/许可整理描述为再次运行了全部测试。
