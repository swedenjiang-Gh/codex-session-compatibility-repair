# Codex Session Compatibility Repair 设计规格

## 目标

提供一个可双击运行的 Windows 单文件 EXE，扫描 Codex 历史会话中的跨模型不兼容内部推理记录，让用户选择一个或多个任务，在保留可见对话的前提下安全修复，并可选择是否创建备份。

## 用户流程

1. 双击 `CodexSessionCompatibilityRepair.exe`。
2. 若 Codex/ChatGPT 正在运行，工具先等待相关进程全部退出，最长 30 分钟；这是因为 Codex 可能独占会话文件。
3. 工具扫描 `%USERPROFILE%\.codex\sessions` 和 `%USERPROFILE%\.codex\archived_sessions`，仅显示包含非空 `response_item.payload.type = "reasoning"` 内容的候选任务，包括序号、任务 ID、日期、标题和命中数量。
4. 用户输入一个或多个序号，或输入 `ALL` 选择全部候选任务。
5. 用户选择：
   - `1`：修复并备份，确认词为 `APPLY`；
   - `2`：修复但不备份，确认词为 `APPLY-NO-BACKUP`。
6. 工具显示最终预览并等待正确确认词；其他输入均取消。
7. 写入前再次检查 Codex/ChatGPT 进程；若已重新打开，则再次等待退出。
8. 工具逐个修复、验证并显示结果和日志路径。

## 修复边界

- 只修改 JSONL 中同时满足以下条件的记录：
  - 顶层 `type` 为 `response_item`；
  - `payload.type` 为 `reasoning`；
  - `payload.content` 是非空数组。
- 将目标记录的 `payload.content` 改为空数组。
- 不修改用户消息、助手可见消息、开发者消息、工具调用、工具输出、会话元数据或 `state_5.sqlite`。
- 不读取、显示或写入 API Key、Token、密码和代理配置。

## 安全与恢复

- 修复前重新读取目标文件并核对任务 ID和命中数量，防止扫描后文件变化。
- 带备份模式将每个原始 JSONL 完整复制到 `D:\codex\backups\session-compatibility-repair-<timestamp>`；D 盘不可用时使用 `%USERPROFILE%\codex-backups`。
- 备份后校验 SHA-256 一致。
- 在原文件同目录生成临时文件，完整解析并验证后使用原子替换。
- 校验总行数不变、非目标行字节不变、目标记录全部清空且修改数符合预览。
- 无备份模式保留相同的临时文件与写入前验证，但明确提示操作不可回退。
- 任一文件失败时不替换该文件；其他已完成文件保留成功状态并记录日志。

## 技术方案

- Python 3.11+ 标准库实现核心逻辑和控制台交互，不增加运行时第三方依赖。
- 使用 `unittest` 覆盖扫描、选择、备份、无备份、文件变化拒绝、进程等待和 EXE 冒烟测试。
- 使用 PyInstaller `--onefile --console` 构建独立 Windows EXE；本机不安装缺失依赖，由 GitHub Actions Windows runner 完成构建和 EXE 冒烟测试。
- 仓库路径：`D:\GitHub\codex-session-compatibility-repair`。
- GitHub 仓库：当前登录账号下的公开 `codex-session-compatibility-repair`。

## 发布边界

- 公开仓库包含源码、测试、构建脚本、README、许可证和设计/实施文档。
- `.gitignore` 排除 `dist/`、`build/`、真实会话、备份、日志、缓存和本机环境文件。
- 首次交付只推送源码仓库；不创建 GitHub Release，也不上传真实会话或本机构建日志。

## 验收标准

- 双击 EXE 可完成扫描、选择、备份选项、确认、等待退出、修复和结果展示。
- fixture 测试证明只清空目标 reasoning 内容，所有非目标行保持完全一致。
- 选择备份时产生可验证的原文件副本；选择不备份时不创建备份目录。
- 取消、错误确认、目标文件变化或 Codex 退出超时均不修改会话。
- 全部自动化测试通过，EXE 在无 Python PATH 的隔离环境中通过冒烟测试。
- Git 历史干净，公开仓库不含敏感数据并成功推送。
