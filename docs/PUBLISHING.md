<!-- SPDX-FileCopyrightText: 2026 Tkkdy -->
<!-- SPDX-License-Identifier: MIT -->
# v0.1.0 发布说明 / Publication

公开目标为 [Tkkdy/attention-router](https://github.com/Tkkdy/attention-router)，默认 main，正常 v0.1.0 Release，非 Pre-release。Description、Topics 及分组件许可记录在 [release-metadata.json](../release-metadata.json)。

唯一代码基线为已独立复审通过的 offline-final2。所有者于 2026-10-20 批准首次源码公开，并明确将精确候选真机验收和真实硬件照片留作后续工作；未完成状态必须保留披露。这项决定替代历史离线材料中的“硬件验收完成后才可发布源码”条件，不授权操作现用设备。

## 发布顺序

1. 保存并核对旧私有仓库身份、权限和全部 refs；先更新所有私人工作区的 fetch/push 地址，再保留 Private 改名。私人历史不得进入公开仓库。
2. 从已核验公开 ZIP 建立独立干净初始历史，核对 GIT_FILES、LICENSE_MAP、SOURCE_MANIFEST 和实际提交字节，使用 GitHub noreply 提交邮箱。
3. 推送 main；Issues 与 PR 开放，Discussions 暂不开启。运行已有轻量 CI，记录实际结果；仅可修复明确的 CI 环境问题，业务或安全问题必须停止报告。
4. 对应 main 提交 CI 通过后才创建 v0.1.0 标签和正常 Release；核实匿名公开访问及自动源码归档。

## 附件与限制

只提供仓库源码和 GitHub 自动生成的 ZIP / tar.gz 归档，不上传外部审查包、review-private、运行日志、数据库、Flash/NVS 备份或私人配置。

不提供预编译 .bin：当前 Wi-Fi/Hub 配置在编译期生效，没有已验收的通用首次配置流程，精确候选真机验收也未完成。二进制需要新增配置能力及对应安全、硬件和许可证核验，不为 v0.1.0 开发这些功能。

私人设备有历史运行记录，但不能替代精确公开固件验收。NVS 中文标题离线恢复、两项旧 JSON 迁移失败和实验集成限制见 [LIMITATIONS](LIMITATIONS.md)。原板刷写 No-Go 不变。真实硬件照片以后补充，不能用概念图冒充。

## English

This source release uses independently reviewed offline-final2 and a new initial Git history. The owner approved publication with exact-firmware hardware acceptance and a real hardware photo still outstanding. Those limitations are disclosed, not represented as passed. CI must pass before tagging. Only repository source and GitHub-generated archives are offered; there are no precompiled firmware assets or private review materials. Device operations require separate authorization.
