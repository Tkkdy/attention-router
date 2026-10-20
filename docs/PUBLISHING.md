<!-- SPDX-FileCopyrightText: 2026 Tkkdy -->
<!-- SPDX-License-Identifier: MIT -->
# 源码发布 / Source publication

公开仓库为 [Tkkdy/attention-router](https://github.com/Tkkdy/attention-router)。已有 v0.1.0 Tag/Release 保留；main 可含后续维护。

1. 仅审阅公开分支的必要差异，不引入私人历史或运行数据。
2. 同步 GIT_FILES.txt、LICENSE_MAP.json、SOURCE_MANIFEST.json；保留第三方许可和通知。
3. 使用独立数据运行 [CI 检查](CI.md)，明确已知失败及未测范围。
4. 通过 PR 和对应 Actions 后合并；源码发行需对应提交的 CI 通过。
5. 只发布源码归档，不包含凭据、数据库、日志、审查包、个人构建或 Flash/NVS 备份。

不提供预编译固件：Wi-Fi/Hub 配置在编译期生效，通用首次配置及精确固件硬件验收未完成。软件通过不等于硬件验收，见 [验证](VALIDATION.md) 和 [限制](LIMITATIONS.md)。

English: Review only intended public changes, update source/license inventories, run the documented checks, and merge through a passing PR. Keep existing releases immutable. Source archives exclude private history, credentials, runtime data and personal binaries. No precompiled firmware or hardware acceptance is implied.
