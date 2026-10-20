<!-- SPDX-FileCopyrightText: 2026 Tkkdy -->
<!-- SPDX-License-Identifier: MIT -->
# 轻量 CI / Limited CI

本 workflow 是首发的有限检查集，不是“全项目测试通过”声明。历史离线命令结果保留，平台当前状态见 [GitHub Actions](https://github.com/Tkkdy/attention-router/actions)。正式标签只在对应 main 提交 CI 通过后创建；最终候选真机验收另行进行。

## 检查范围

- `python -B ci/check_source.py`：所有 Python 文件的语法解析（不导入应用）；禁止私有/运行产物；核对 `SOURCE_MANIFEST.json` 的文件、字节数和 SHA-256，以及 `GIT_FILES.txt` 的完整公开清单。manifest 不记录自身哈希，GIT_FILES 包含自身及 manifest。合法新增文件应在审查后更新清单，不会仅因文件名不在旧版清单就被判为私密。
- `python -B ci/run_basic.py`：19 项已有基础回归。包括 Scene 快照/来源/读取副作用、LAN 鉴权、可选 Radar 的 STALE 范围、NOW/QUEUE/DIGEST/DROP 路由、ACK 幂等、事件修订、事务回滚、采样线程取消/异常和慢诊断。明确的测试名称保存在该脚本 `TESTS` 列表中。
- `node hub/test_console_runtime.cjs`：现有 Console 脚本在 mock DOM 与合成 transport 中运行，覆盖不可达/恢复、快照展示、ACK 冲突重试等；没有浏览器、真实服务或外部请求。

测试驱动将必要 Hub 源文件复制到新的临时目录，因为 `app.py` 的全局实例在导入时可能创建默认 `.build` 数据。临时目录与新建合成数据在结束后清理，候选树和私人运行数据均不作为测试数据库。

子进程只继承必要 Windows 启动变量，隔离 HOME、USERPROFILE、APPDATA、TEMP；不继承模型凭据或应用环境配置，Radar URL 为空。WINDIR 指向不存在的字体目录，基础集不依赖微软雅黑。应用 socket bind/connect 被拒绝；仅允许 Windows 标准库 `socketpair` 内部自唤醒连接，以便 asyncio/TestClient 正常工作。这是回归隔离护栏，不是恶意代码安全沙箱。

## 明确未纳入的已知失败与其他检查

以下两项旧 JSON 迁移测试仍保留原实现和断言，已知失败未被修复，也没有改成 expectedFailure/skip：

1. `test_attention.AttentionTests.test_atomic_migration_keeps_json_and_restarts`：历史结果为 `IndexError`。
2. `test_attention.AttentionTests.test_invalid_migration_is_atomic`：历史结果为未产生预期 `ValueError`。

有限基础集启动时会明确打印这两项未纳入的已知失败。19/19 只代表本页列出的集合通过，不代表完整 test_attention 或全部回归通过。不得把绿色基础 CI 用作“迁移已修复”的证据。

真实系统字体的存在检查、6 秒并发/锁持有压力试验、真实前台采样、Bot/OAuth/模型付费 API、外部 Tibo/Radar、固件编译、串口、Flash/NVS 及 ESP32 真机验收都不在本 workflow 中。其已有证据和限制见 [VALIDATION.md](VALIDATION.md) 与 [LIMITATIONS.md](LIMITATIONS.md)。

## 本地运行

使用 Python 3.13、已有兼容 Node.js（workflow 指定 Node 24）。在新建且不含运行产物的公开源码目录执行：

```powershell
python -m pip install --disable-pip-version-check --only-binary=:all: -r requirements.lock.txt
python -B ci/check_source.py
python -B ci/run_basic.py
node hub/test_console_runtime.cjs
```

依赖已安装时不要重复安装。`--syntax-only` 仅供清单仍在修订时检查语法与私有文件；正式 CI 不使用该选项。

历史离线准备在 Windows / Python 3.13.7 / Node 24.19.0 环境复用锁定依赖，19 项基础回归和 Console fixture 检查通过。该历史记录不代表远端 Actions；平台运行结果以对应提交的 Actions 记录为准。

## 权限与供应链边界

workflow 只响应 `push` / `pull_request`，使用 GitHub 托管 `windows-latest`，权限仅 `contents: read`。不使用 `pull_request_target`、仓库 secrets、环境 secrets、self-hosted runner、上传产物、发布或缓存写入；checkout 不持久化凭据。不要给此基础作业添加部署凭据。

Python 依赖精确锁定版本并要求 wheel，但当前 lock 不是带 wheel 哈希的供应链锁文件。安装依赖、获取 Actions/Python/Node 需要联网；测试本身不调用外部业务 API。Actions 固定到经官方 release 页面核对的完整提交 SHA：

- [actions/checkout v4.2.2](https://github.com/actions/checkout/commit/11bd71901bbe5b1630ceea73d27597364c9af683)
- [actions/setup-python v5.6.0](https://github.com/actions/setup-python/commit/a26af69be951a213d495a4c3e4e4022e16d87065)
- [actions/setup-node v4.4.0](https://github.com/actions/setup-node/commit/49933ea5288caeca8642d1e84afbd3f7d6820020)

checkout 通过该 step 的临时 Git 配置关闭自动换行转换，以保留 manifest 的字节依据；不修改本机或全局 Git 配置。首次公开提交也必须保留已批准源文件字节，或先完成经过审查的统一规范化并重建 manifest。

## English summary

This is a **limited offline regression suite**, not a full test pass or hardware acceptance. It parses Python syntax without importing applications, checks the reviewed manifest/file inventory, runs 19 named synthetic regressions in a disposable Hub copy, and exercises the real Console script with a mock DOM/transport. No system font, device, credential or paid model is required. Child process configuration is isolated; application socket IO is rejected, except the standard library's internal Windows asyncio wakeup socketpair.

The two named legacy JSON migration failures above remain unchanged and are explicitly outside this basic set. Font-presence tests, long contention tests, live integrations, firmware builds and hardware acceptance are also outside this workflow. Historical local commands passed; consult [GitHub Actions](https://github.com/Tkkdy/attention-router/actions) for the actual result of each published commit. The workflow uses hosted Windows, Python 3.13, Node 24, pinned dependency versions, SHA-pinned official actions, read-only contents permission and no persisted checkout credential. A future clean runner still needs network access to download public tools/dependencies. New legitimate files require reviewed manifest/list updates, not removal merely because they are new.
