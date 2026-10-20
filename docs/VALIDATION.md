# 验证与边界

公开源码的确切文件身份见 SOURCE_MANIFEST.json，当前平台结果见 [GitHub Actions](https://github.com/Tkkdy/attention-router/actions)。

## 本轮功能整合（2026-10-20）

- 使用临时源码拷贝、全新数据库和合成任务；未连接已有业务服务、模型账号或设备。
- 定向 Tibo、上下文、AI Interrupt、Grok/Gateway、Todo Core 与投影回归：67/67。
- CI 基础集合增加 Tibo、上下文和 AI Interrupt 用例；运行范围见 [CI](CI.md)。
- HTTP Agent 示例单独验证鉴权、Todo/Current、提醒、ACK、相同请求重放、丢响应重试与 409 冲突。
- Console 使用实际脚本加 mock DOM；DeepSeek 适配器使用合成调用，无付费模型。
- 固件文件与公开 v0.1.0 一致，本轮未重编译或刷写。

## 保留的历史证据与失败

既有稳定性定向检查 9/9，核心回归 86/88；两项旧 JSON 迁移失败保留：

- test_attention.AttentionTests.test_atomic_migration_keeps_json_and_restarts：IndexError。
- test_attention.AttentionTests.test_invalid_migration_is_atomic：未抛出预期 ValueError。

仅支持新数据目录；本轮未重构迁移，也不宣称全套测试通过。基础集合明确排除上述两项，不隐藏其状态。历史 v0.1.0 的 [有限 Actions 运行](https://github.com/Tkkdy/attention-router/actions/runs/39403342507) 成功不代表后续代码已通过，后续提交以各自运行结果为准。

已有稳定性修复保留：串行采样与配置锁、工作线程取消排空、线程局部 SQLite、只读 overview 快照、事务内 Scene 发布、脱敏慢请求日志。长事务和过载仍可能超过客户端超时；health 正常不能证明 Scene/overview 正常。

历史官方固件工具链构建曾通过：Arduino CLI 1.5.1、ESP32 Core 3.3.1、GxEPD2 1.6.9、ArduinoJson 7.4.2、Adafruit GFX 1.12.6 / BusIO 1.17.4；FQBN esp32:esp32:esp32。源码许可和后续 Hub 改动不构成一次新的固件构建证据。

## 未测范围

精确公开固件的实屏、Wi-Fi、NVS/断电恢复、实体硬件；真实 Windows 前台采样；独立 GrokBot/DeepSeekBot 聊天网页、MCP/OAuth/Tunnel 与付费模型端到端均未在本轮验收。Hub 发布 Scene 不等于设备收到/显示。详见 [硬件](HARDWARE.md)、[限制](LIMITATIONS.md) 与 [Agent 集成](AGENTS.md)。
