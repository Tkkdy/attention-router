<!-- SPDX-FileCopyrightText: 2026 Tkkdy -->
<!-- SPDX-License-Identifier: MIT -->

## 问题与改动 / Problem and change

<!-- 说明一个明确问题、改动范围及关联 Issue（如有）。/ Describe one concrete problem, the scope, and a related issue if any. -->

## 验证 / Validation

<!-- 写实际命令、结果和未测原因。区分合成软件测试、私人版本历史记录及最终候选真机。/ Give actual commands, results, and reasons for untested areas. Distinguish synthetic software tests, private-build history, and final-candidate hardware evidence. -->

## 剩余风险 / Remaining risks

<!-- 不要求通过刷机、操作真实待办或调用付费服务来补证。/ Do not operate hardware, real tasks, or paid services merely to fill this section. -->

## 检查 / Checklist

- [ ] 改动范围明确，无无关重构或隐含新功能。/ The change is focused, without unrelated refactors or hidden new behavior.
- [ ] 不含私人任务、凭据、网络配置、真实数据库或 NVS/Flash 备份。/ No private tasks, credentials, network settings, real databases, or NVS/Flash backups are included.
- [ ] 保留真实测试失败和未测范围，没有修改断言来制造全绿。/ Actual failures and untested areas are reported; assertions were not weakened to manufacture a pass.
- [ ] 保留适用 SPDX、版权和第三方通知；新增材料说明来源及许可。/ Applicable SPDX identifiers, attribution, and third-party notices are preserved; new material has provenance and licensing details.
- [ ] 涉及用户说明时，中英文文档已同步或明确列出待补项。/ User-facing Chinese and English documentation is aligned, or gaps are explicitly listed.

<!-- 最终候选真机验收尚未完成；测试通过不自动扩大支持范围。首发目标为经典 ESP32 + GDEY042Z98，XIAO ESP32S3 不在首发范围。/ Final-candidate hardware acceptance remains incomplete; passing tests does not broaden support. The launch target is classic ESP32 + GDEY042Z98, not XIAO ESP32S3. -->
