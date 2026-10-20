<!-- SPDX-FileCopyrightText: 2026 Tkkdy -->
<!-- SPDX-License-Identifier: MIT -->
# 有限 CI / Limited CI

当前结果见 [GitHub Actions](https://github.com/Tkkdy/attention-router/actions)。此 workflow 不是全项目、真实 Bot 或硬件验收。

~~~powershell
python -B ci/check_source.py
python -B ci/run_basic.py
node hub/test_console_runtime.cjs
python -B examples/test_agent_http_demo.py
node --test integrations/deepseek_bot/gateway-client.test.mjs
~~~

## 范围

- source：解析 Python 语法、不导入应用；拒绝私密/生成文件；核对清单、字节数与 SHA-256。manifest 不记录自身哈希，GIT_FILES 包含所有公开文件。
- basic：48 项合成测试，包括原 19 项稳定性/路由/Scene 检查，加 Tibo 自动页、工作上下文与 AI Interrupt。名称以脚本 TESTS 为准。
- Console：实际脚本加 mock DOM，覆盖不可达/恢复、Scene 快照、ACK 冲突/重放、取消与上下文。
- Agent HTTP：7 项真实 loopback HTTP 测试，包括鉴权、Todo/Current、提醒、ACK、幂等、丢失响应与修订冲突。
- DeepSeek：11 项适配器测试，不调用模型。

basic 在一次性源码拷贝和临时合成数据库中执行。子进程隔离 HOME、APPDATA、TEMP，不继承业务凭据，禁用外部来源与系统字体。应用 socket bind/connect 被拒绝，仅允许 Windows asyncio 标准库自唤醒 socketpair。HTTP 示例另用随机 loopback 端口，拒绝外部连接和保留的 8000。测试护栏不等于恶意代码安全沙箱。

## 保留的失败与未测范围

两项旧 JSON 迁移测试保留原代码/断言，未改为 skip 或 expectedFailure，但不属于 basic：

- test_attention.AttentionTests.test_atomic_migration_keeps_json_and_restarts：历史 IndexError。
- test_attention.AttentionTests.test_invalid_migration_is_atomic：历史未产生预期 ValueError。

只支持新数据目录，绿色 CI 不证明迁移已修复。真实前台采样、字体存在、长时间压力、模型/Bot/OAuth/Tunnel、外部 Tibo/Radar、固件编译、ESP32/NVS/实屏不在此 workflow。历史证据见 [验证](VALIDATION.md)。

## 平台与权限

GitHub 托管 windows-latest、Python 3.13、Node 24。按 requirements.lock.txt 安装锁定版本 wheel；依赖已安装时不需重复安装。该锁文件未包含 wheel 哈希。工具/依赖下载需要网络，测试不调用外部业务 API。

workflow 只响应 push/pull_request，contents:read，不使用 secrets、pull_request_target、自托管 runner 或发布操作；checkout 不持久化凭据。官方 Actions 固定完整 SHA。保留源码精确换行字节，不修改本地/全局 Git 配置。合法改动经审查后需同步文件/许可/哈希清单，正式检查不能用 --syntax-only 替代。

English: This is a limited suite, not a full regression or hardware pass. It checks exact source inventories, 48 isolated basic cases, the Console fixture contract, seven synthetic loopback HTTP cases and eleven DeepSeek adapter cases. Two legacy migration failures remain outside basic. No paid model or hardware is required. Hosted CI has read-only contents permission and no credentials; public dependency downloads still require network access.
