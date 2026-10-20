<!-- SPDX-FileCopyrightText: 2026 Tkkdy -->
<!-- SPDX-License-Identifier: MIT -->
# Attention Router v0.1.0 — Release Notes

**v0.1.0 正常源码 Release，非 Pre-release。** 基于已独立复审通过的 `offline-final2`，可以按教程从源码构建和部署。所有者批准先发布源码；精确公开候选固件的最终真机验收及真实硬件宣传照片仍待补，不声称硬件已通过验收。

> A local-first AI attention router powered by ESP32 e-paper, bringing tasks, work context, and important alerts into focus.

Attention Router是Personal Agent在物理世界的注意力交互终端：通过本地Hub、Web Console和指定ESP32墨水屏，把任务、工作上下文及重要提醒带到视线中。它使用确定性路由，不是完整通用Agent生命周期管理器。

## 内容 / Included

- Home、Workspace、Interrupt，Todo/Current/Next展示，Windows前台上下文和手动覆盖，NOW/QUEUE/DIGEST/DROP路由。
- Web Console与提醒ACK；ACK不等于任务完成。可信LAN `/scene` / `/health` 和缓存、STALE、恢复稳定窗口。
- GrokBot/DeepSeekBot、MCP/OAuth、自然语言Resolver、Codex额度、Tibo Reset和可选外部源作为Experimental分别说明，未承诺独立安装和真实客户端端到端全部通过。
- 完整中文/英文README、安装排查、精简Roadmap、真实合成数据Console截图和源码架构图、轻量CI及社区模板。
- Copyright (c) 2026 Tkkdy；独立自有Hub/Web/工具MIT，原创固件GPL-3.0-only，第三方许可保持。允许按适用条款商业使用。

正式发布相对 offline-final2 更新发布状态文档和对应清单，并给 CI 依赖安装命令添加 YAML 引号，修复首次 Actions 解析失败；实际命令、依赖版本、业务、固件和测试逻辑不变。此前稳定性、STALE、字体降级及数据隔离修订完整保留。

## 验证与限制 / Validation and limits

历史M1.1-stability1隔离稳定性测试9/9、核心86/88；两项旧JSON迁移失败保留。不支持将私人/生产旧数据直接导入。六秒事务外采样测试的真实本地HTTP最大耗时为health 15.7ms、scene 53.3ms、overview 45.9ms；人为持锁六秒时业务接口仍可能超过设备五秒超时。健康接口成功不是业务接口响应保证。

CI 是有限基础集，范围见[CI说明](docs/CI.md)，历史记录见[验证记录](docs/VALIDATION.md)，平台实际结果见[GitHub Actions](https://github.com/Tkkdy/attention-router/actions)。发布标签须在对应 main 提交的首次 CI 通过后创建；绿色 CI 不代表完整回归或硬件验收通过。

私人设备离线冷启动曾出现中文任务短编号占位，联网恢复；身份和根因未闭环。公开候选核心真机验收仍待完成；NVS中文离线恢复可作为已知限制而非无限延期条件，不能宣称它已通过。原板写入No-Go不变。`Today`是已有顺序中未完成任务的截取，不是按今天/到期日筛选；DIGEST不是AI摘要。

字体缺失有ASCII降级；不分发Windows字体。外部源依赖Internet Probe/NTP/日期等条件，Bot/模型可能收费，未提供本地开源权重执行路径。长期可靠性未经长期真机证明。计划中的ChatGPT/Codex完成通知、Agent Inbox及更广泛个人上下文未实现。

## 安装与附件 / Install and assets

从[中文README](README.md)或[English README](README_EN.md)开始，使用全新目录和锁定依赖。支持目标为经典ESP32及指定屏幕/转接板，Seeed XIAO ESP32S3属于后续计划。

预编译固件**暂不提供**：缺少已验收的通用首次配置路径及最终精确固件真机记录；源码用户按教程填自己的本地配置构建。没有虚假二进制下载链接，也不附私人编译产物。未来二进制须单独满足配置安全与GPL/LGPL对应源码/第三方义务。

源码通过公开仓库和 GitHub 自动生成的 ZIP / tar.gz 源码归档提供，不另外上传固件、私人审查包或备份。Issues 与 PR 开放，Discussions 暂不开启。详细许可见[LICENSE](LICENSE)，实验矩阵和 Roadmap 见[FEATURES](docs/FEATURES.md)。

### English release summary

A local-first attention interface for a Personal Agent, with a Python Hub, Web Console, and a specified classic ESP32 e-paper display. The release includes implemented routing/display software, explicitly experimental integrations, bilingual documentation, source-grounded visuals, and limited offline CI checks. It does not implement general Agent lifecycle tracking.

This is a normal v0.1.0 source release, not a Pre-release, based on independently reviewed offline-final2. Build and deploy from source. Historical private-device operation does not establish acceptance of the exact public firmware: final hardware acceptance and a real hardware product photo remain outstanding, and the owner approved source publication with those limitations. Known legacy migration failures and offline Chinese-title cache limitations remain disclosed. Experimental integrations require their own configuration and deployment; ChatGPT/Codex completion alerts and Agent Inbox are not implemented. No precompiled firmware is supplied. GitHub provides automatic source archives. Hardware support does not include XIAO ESP32S3 at launch.
