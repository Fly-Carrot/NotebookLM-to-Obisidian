#!/usr/bin/env python3
"""Export local Antigravity conversations into clean Obsidian-friendly markdown.

Strategy:
1) Discover conversation ids from ~/.gemini/antigravity/conversations/*.pb
2) For each id, gather readable mirrors from:
   - ~/.gemini/antigravity/brain/<id>/*.md
   - ~/Antigravity_Skills/global-agent-fabric/workflows/imported/antigravity-<id>.md
3) Produce one consolidated markdown per conversation id.
4) If no readable mirror exists, emit metadata placeholder so no conversation is lost.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ANTIGRAVITY_ROOT = Path.home() / ".gemini" / "antigravity"
DEFAULT_GAF_ROOT = Path.home() / "Antigravity_Skills" / "global-agent-fabric"
DEFAULT_OUTPUT_DIR_NAME = "Antigravity"

PRIMARY_MD_ORDER = [
    "task.md",
    "implementation_plan.md",
    "walkthrough.md",
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


def extract_printable_snippets(data: bytes, max_items: int = 20) -> list[str]:
    snippets: list[str] = []
    for m in re.finditer(rb"[ -~]{20,}", data):
        text = m.group(0).decode("utf-8", errors="ignore").strip()
        if text and text not in snippets:
            snippets.append(text)
        if len(snippets) >= max_items:
            break
    return snippets


@dataclass
class ExportStats:
    conversations_found: int = 0
    files_written: int = 0
    files_skipped: int = 0
    mirrored_readable: int = 0
    metadata_only: int = 0


def discover_conversation_files(antigravity_root: Path) -> list[Path]:
    conv_dir = antigravity_root / "conversations"
    if not conv_dir.exists():
        return []
    return sorted(conv_dir.glob("*.pb"), key=lambda p: p.stat().st_mtime, reverse=True)


def gather_md_sources(conv_id: str, antigravity_root: Path, gaf_root: Path) -> list[Path]:
    sources: list[Path] = []
    brain_dir = antigravity_root / "brain" / conv_id
    if brain_dir.exists():
        for name in PRIMARY_MD_ORDER:
            p = brain_dir / name
            if p.exists() and p.is_file():
                sources.append(p)
        extras = sorted(
            [
                p
                for p in brain_dir.glob("*.md")
                if p.name not in PRIMARY_MD_ORDER
                and not p.name.endswith(".metadata.json")
                and ".resolved" not in p.name
            ]
        )
        sources.extend(extras)

    imported = gaf_root / "workflows" / "imported" / f"antigravity-{conv_id}.md"
    if imported.exists() and imported.is_file():
        sources.append(imported)

    unique: dict[str, Path] = {}
    for p in sources:
        unique[str(p)] = p
    return list(unique.values())


def render_conversation_markdown(
    conv_file: Path,
    conv_id: str,
    md_sources: list[Path],
) -> str:
    mod_iso = datetime.fromtimestamp(conv_file.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        "---",
        f"conversation_id: {conv_id}",
        f"pb_path: {conv_file}",
        f"pb_size_bytes: {conv_file.stat().st_size}",
        f"pb_modified_at: {mod_iso}",
        f"readable_mirror_count: {len(md_sources)}",
        f"exported_at: {now_iso()}",
        "---",
        "",
        f"# Antigravity Conversation {conv_id}",
        "",
    ]

    if md_sources:
        for src in md_sources:
            raw = src.read_text(encoding="utf-8", errors="ignore")
            cleaned = normalize_markdown_body(raw)
            title = sanitize_name(src.name)
            lines.extend([
                f"## Source: {title}",
                "",
                f"_Original path: `{src}`_",
                "",
                cleaned,
                "",
            ])
    else:
        data = conv_file.read_bytes()
        snippets = extract_printable_snippets(data, max_items=30)
        lines.extend([
            "## Binary Conversation Placeholder",
            "",
            "This conversation is stored as binary `.pb` and no readable markdown mirror was found on this machine.",
            "",
            "### Metadata",
            "",
            f"- File: `{conv_file}`",
            f"- Size: `{conv_file.stat().st_size}` bytes",
            f"- Modified: `{mod_iso}`",
            "",
        ])
        if snippets:
            lines.extend(["### Extracted Text Snippets (best-effort)", ""])
            lines.extend([f"- {s}" for s in snippets])
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def export_conversations(
    antigravity_root: Path,
    gaf_root: Path,
    out_root: Path,
    dry_run: bool,
    stats: ExportStats,
) -> None:
    conv_files = discover_conversation_files(antigravity_root)
    stats.conversations_found = len(conv_files)
    print(f"[INFO] Found {len(conv_files)} Antigravity conversation .pb files.")

    if not dry_run:
        out_root.mkdir(parents=True, exist_ok=True)

    index_lines = [
        "# Antigravity Conversation Export",
        "",
        f"- Exported At: `{now_iso()}`",
        f"- Antigravity Root: `{antigravity_root}`",
        f"- GAF Root: `{gaf_root}`",
        f"- Conversation Count: `{len(conv_files)}`",
        "",
        "## Conversations",
        "",
    ]

    for idx, conv_file in enumerate(conv_files, start=1):
        conv_id = conv_file.stem
        md_sources = gather_md_sources(conv_id, antigravity_root=antigravity_root, gaf_root=gaf_root)
        if md_sources:
            stats.mirrored_readable += 1
        else:
            stats.metadata_only += 1

        out_name = f"{idx:04d}-{conv_id}.md"
        out_path = out_root / out_name
        content = render_conversation_markdown(conv_file=conv_file, conv_id=conv_id, md_sources=md_sources)
        changed = write_text_if_changed(out_path, content, dry_run=dry_run)

        if changed:
            stats.files_written += 1
        else:
            stats.files_skipped += 1

        marker = "readable" if md_sources else "metadata-only"
        index_lines.append(f"- [{conv_id}]({out_name}) - {marker}")

        if idx % 10 == 0 or idx == len(conv_files):
            print(f"[PROGRESS] {idx}/{len(conv_files)}")

    write_text_if_changed(out_root / "INDEX.md", "\n".join(index_lines) + "\n", dry_run=dry_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export local Antigravity conversations to markdown.")
    parser.add_argument("--antigravity-root", default=str(DEFAULT_ANTIGRAVITY_ROOT), help="Root of local antigravity runtime.")
    parser.add_argument("--gaf-root", default=str(DEFAULT_GAF_ROOT), help="Global-agent-fabric root for imported readable mirrors.")
    parser.add_argument("--vault-root", required=True, help="Obsidian vault root.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR_NAME, help="Output directory name under vault root.")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no file writes.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    antigravity_root = Path(args.antigravity_root).expanduser()
    gaf_root = Path(args.gaf_root).expanduser()
    vault_root = Path(args.vault_root).expanduser()
    out_root = vault_root / args.output_dir

    if not antigravity_root.exists():
        print(f"[ERROR] Antigravity root not found: {antigravity_root}")
        return 1
    if not vault_root.exists():
        print(f"[ERROR] Vault root not found: {vault_root}")
        return 1

    stats = ExportStats()
    export_conversations(
        antigravity_root=antigravity_root,
        gaf_root=gaf_root,
        out_root=out_root,
        dry_run=args.dry_run,
        stats=stats,
    )

    print("\n[RESULT]")
    print(f"  conversations_found: {stats.conversations_found}")
    print(f"  files_written:       {stats.files_written}")
    print(f"  files_skipped:       {stats.files_skipped}")
    print(f"  readable_mirrored:   {stats.mirrored_readable}")
    print(f"  metadata_only:       {stats.metadata_only}")
    print(f"  output_root:         {out_root}")
    print("[DONE] 100%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
