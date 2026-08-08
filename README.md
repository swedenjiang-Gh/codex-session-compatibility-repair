# Codex Session Compatibility Repair

一个用于修复 Codex 跨模型历史会话兼容问题的 Windows 工具。典型场景是：同一个长任务先使用 DeepSeek，随后切换到 GPT，继续对话时出现：

```text
Invalid 'input[n].content': array too long. Expected an array with maximum length 0
```

工具会清空旧模型留下的非空 `reasoning` 内部内容，并把旧代理生成的 `web_search_call.id = "call_..."` 转换成 GPT Responses API 使用的 `ws_...`。用户消息、助手可见回复、开发者消息、搜索动作与会话元数据保持不变。

## 使用方法

1. 从 GitHub Actions 的最新成功构建下载 `CodexSessionCompatibilityRepair.exe`。
2. 双击运行。
3. 如果 Codex 正在运行，按提示完全退出；工具会自动等待，不需要重新启动工具。
4. 从扫描结果中输入一个或多个任务序号，或输入 `ALL`。
5. 选择修复模式：
   - `1`：修复并备份；输入 `APPLY` 确认。
   - `2`：修复但不备份；输入 `APPLY-NO-BACKUP` 确认。
6. 等待逐任务校验和修复完成，再重新打开 Codex 验证。

默认备份目录是 `D:\codex\backups`；如果没有 D 盘，则使用 `%USERPROFILE%\codex-backups`。日志默认写到备份目录旁的 `logs`。

## 安全边界

- 仅处理 `%USERPROFILE%\.codex\sessions` 和 `archived_sessions` 下的 JSONL。
- 把非空 `response_item.payload.type = "reasoning"` 的 `payload.content` 改为空数组。
- 把 `response_item.payload.type = "web_search_call"` 且以 `call_` 开头的 `payload.id` 改为 `ws_` 前缀。
- 非目标行保持字节级不变。
- 写入前重新核对文件大小、修改时间、SHA-256 和命中数量。
- 临时文件完整验证后才替换原文件。
- 不修改 `state_5.sqlite`、provider 标签、`config.toml` 或任何密钥。
- 无备份模式不可自动回退，必须使用更强确认词。

## 从备份恢复

关闭 Codex，将备份目录中的对应 JSONL 文件复制回日志记录的原始路径。恢复前建议另存当前文件，避免覆盖之后新增的会话内容。

## 本地测试

```powershell
python -m unittest discover -s tests -v
```

## 构建 EXE

本机需有 Python 3.11+ 和 `requirements-build.txt` 中固定版本的 PyInstaller：

```powershell
python -m pip install -r requirements-build.txt
pwsh.exe -NoLogo -NoProfile -NonInteractive -File .\build-exe.ps1
python tests\exe_fixture.py dist\CodexSessionCompatibilityRepair.exe
```

公开仓库的 GitHub Actions 会在 Windows runner 上自动完成测试、构建和 EXE 冒烟验证，并提供构建产物下载。

## 限制

本工具解决的是 DeepSeek 等模型留下的 reasoning 内容和旧格式 Web Search ID 与 GPT Responses API 不兼容的问题。若错误来自代理对其他工具调用、`previous_response_id` 或其他协议字段的转换，仍需代理自身修复跨模型历史迁移逻辑。

## License

MIT

