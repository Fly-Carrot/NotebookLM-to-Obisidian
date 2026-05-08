# NotebookLM-to-Obisidian

[English](README.en.md) | [Simplified Chinese](README.zh-CN.md)

一个极简的一键同步工具：从 NotebookLM 同步到 Obsidian。

![NotebookLM-to-Obisidian App Icon](assets/app-icon.png)

## 快速开始

```bash
cd "/Users/david_chen/Desktop/MCP_Hub/Obsidian Transfer"
./scripts/setup_env.sh
./Obsidian_Transfer_venv/bin/nlm login
./scripts/run_full_sync.sh --vault-root "/Users/david_chen/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Memory"
```

## 导出结构

```text
N2O Export/
  NotebookLM/
  Antigravity/
```

## 核心功能

- 菜单栏应用：`Login`、`Set Path`、`Sync`、`Quit`
- 一体化同步：NotebookLM + Antigravity 导出
- 进度条和状态更新
- Markdown 可读性清洗

## 完整文档

查看双语完整版文档：[README.md](README.md)

[English](README.en.md) | [Simplified Chinese](README.zh-CN.md)
