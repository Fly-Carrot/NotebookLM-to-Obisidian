#!/usr/bin/env python3
"""Export local Antigravity chat markdown into clean Obsidian-friendly docs."""

from __future__ import annotations

import argparse
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SOURCE_ROOT = "/Users/david_chen/Antigravity_Skills"
DEFAULT_OUTPUT_DIR_NAME = "Antigravity Chats"

CHAT_FILE_PATTERNS = [
    "global-agent-fabric/workflows/imported/antigravity-*.md",
    "global-agent-fabric/.agents/**/*.md",
    "**/antigravity-*.md",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_name(name: str, fallback: str = "untitled") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned or fallback


def write_text_if_changed(path: Path, content: str, dry_run: bool) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True


def _is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def _needs_space_between(prev_text: str, next_text: str) -> bool:
    if not prev_text or not next_text:
        return True
    a = prev_text[-1]
    b = next_text[0]
    if _is_cjk_char(a) and _is_cjk_char(b):
        return False
    return True


def normalize_markdown_body(text: str) -> str:
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("\ufeff", "")
        .replace("\u2060", "")
        .replace("\ufffc", "")
        .replace("\u2028", "\n")
        .replace("\u2029", "\n")
    )
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    lines = [line.rstrip() for line in text.split("\n")]
    out: list[str] = []
    plain_buf: list[str] = []
    in_code_block = False

    def flush_plain() -> None:
        nonlocal plain_buf
        if not plain_buf:
            return
        merged = plain_buf[0].strip()
        for seg in plain_buf[1:]:
            nxt = seg.strip()
            if not nxt:
                continue
            if merged.endswith("-") and re.match(r"^[a-z]", nxt):
                merged = merged[:-1] + nxt
            else:
                sep = " " if _needs_space_between(merged, nxt) else ""
                merged += sep + nxt
        merged = re.sub(r"[ \t]+", " ", merged).strip()
        if merged:
            out.append(merged)
        plain_buf = []

    for raw in lines:
        line = raw
        if re.match(r"^\s*[•·‣◦]\s+", line):
            line = re.sub(r"^\s*[•·‣◦]\s+", "- ", line)

        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush_plain()
            in_code_block = not in_code_block
            out.append(line)
            continue

        if in_code_block:
            out.append(line)
            continue

        is_structured = (
            stripped == ""
            or stripped.startswith(("#", ">", "|"))
            or re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped) is not None
            or re.match(r"^(\-|\*|\+)\s+", stripped) is not None
            or re.match(r"^\d+[.)]\s+", stripped) is not None
        )
        if is_structured:
            flush_plain()
            out.append(line)
        else:
            plain_buf.append(line)

    flush_plain()
    normalized = "\n".join(out)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized


@dataclass
class ExportStats:
    files_found: int = 0
    files_written: int = 0
    files_skipped: int = 0


def collect_chat_files(source_root: Path) -> list[Path]:
    found: dict[str, Path] = {}
    for pattern in CHAT_FILE_PATTERNS:
        for path in source_root.glob(pattern):
            if not path.is_file() or path.suffix.lower() != ".md":
                continue
            rel = path.relative_to(source_root).as_posix()
            found[rel] = path
    files = sorted(found.values(), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def export_files(source_root: Path, out_root: Path, dry_run: bool, stats: ExportStats) -> None:
    files = collect_chat_files(source_root)
    stats.files_found = len(files)
    print(f"[INFO] Found {len(files)} Antigravity markdown files.")

    if not dry_run:
        out_root.mkdir(parents=True, exist_ok=True)

    index_lines = [
        "# Antigravity Chat Export",
        "",
        f"- Exported At: `{now_iso()}`",
        f"- Source Root: `{source_root}`",
        f"- File Count: `{len(files)}`",
        "",
        "## Files",
        "",
    ]

    for idx, src in enumerate(files, start=1):
        rel = src.relative_to(source_root)
        base_name = sanitize_name(src.stem)
        out_name = f"{idx:04d}-{base_name}.md"
        out_path = out_root / out_name

        raw = src.read_text(encoding="utf-8", errors="ignore")
        cleaned = normalize_markdown_body(raw)

        content = (
            f"---\n"
            f"source_path: {rel.as_posix()}\n"
            f"source_modified_at: {datetime.fromtimestamp(src.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
            f"exported_at: {now_iso()}\n"
            f"---\n\n"
            f"# {base_name}\n\n"
            f"{cleaned}\n"
        )

        changed = write_text_if_changed(out_path, content, dry_run=dry_run)
        if changed:
            stats.files_written += 1
        else:
            stats.files_skipped += 1

        index_lines.append(f"- [{base_name}]({out_name})")

        if idx % 20 == 0 or idx == len(files):
            print(f"[PROGRESS] {idx}/{len(files)}")

    write_text_if_changed(out_root / "INDEX.md", "\n".join(index_lines) + "\n", dry_run=dry_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export local Antigravity chat markdown files.")
    parser.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT, help="Antigravity source root.")
    parser.add_argument("--vault-root", required=True, help="Obsidian vault root.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR_NAME, help="Output directory name under vault root.")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no file writes.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root).expanduser()
    vault_root = Path(args.vault_root).expanduser()
    out_root = vault_root / args.output_dir

    if not source_root.exists():
        print(f"[ERROR] Source root not found: {source_root}")
        return 1
    if not vault_root.exists():
        print(f"[ERROR] Vault root not found: {vault_root}")
        return 1

    stats = ExportStats()
    export_files(source_root=source_root, out_root=out_root, dry_run=args.dry_run, stats=stats)

    print("\n[RESULT]")
    print(f"  files_found:   {stats.files_found}")
    print(f"  files_written: {stats.files_written}")
    print(f"  files_skipped: {stats.files_skipped}")
    print(f"  output_root:   {out_root}")
    print("[DONE] 100%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
