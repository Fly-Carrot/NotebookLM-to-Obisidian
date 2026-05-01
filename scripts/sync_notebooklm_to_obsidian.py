#!/usr/bin/env python3
"""Sync NotebookLM notebooks into an Obsidian vault structure.

Default output layout:
<vault>/NotebookLM/
  <Notebook Title> [id8]/
    index.md
    Conversations/
      <note>.md
    Sources/
      <source>.md
    Photos/
      <infographic/image files>
    .sync_state.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from json import JSONDecodeError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from notebooklm_tools.core.auth import AuthManager, load_cached_tokens
from notebooklm_tools.core.client import NotebookLMClient
from notebooklm_tools.utils.config import get_config


DEFAULT_VAULT_ROOT = (
    "/Users/david_chen/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Memory"
)
DEFAULT_OUTPUT_DIR_NAME = "NotebookLM"


@dataclass
class SyncStats:
    notebooks_seen: int = 0
    notebooks_synced: int = 0
    notebooks_skipped: int = 0
    notes_written: int = 0
    notes_skipped: int = 0
    sources_written: int = 0
    sources_skipped: int = 0
    photos_written: int = 0
    photos_skipped: int = 0
    errors: int = 0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_name(name: str, fallback: str = "untitled") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned or fallback


def stable_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text_if_changed(path: Path, content: str, dry_run: bool) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True


def cookie_dict(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        out: dict[str, str] = {}
        for item in raw:
            if isinstance(item, dict) and "name" in item and "value" in item:
                out[str(item["name"])] = str(item["value"])
        return out
    return {}


def load_credentials(profile_name: str | None) -> tuple[dict[str, Any], str]:
    chosen_profile = profile_name or get_config().auth.default_profile
    manager = AuthManager(chosen_profile)
    if manager.profile_exists():
        profile = manager.load_profile()
        return (
            {
                "cookies": cookie_dict(profile.cookies),
                "csrf_token": profile.csrf_token or "",
                "session_id": profile.session_id or "",
                "build_label": profile.build_label or "",
            },
            chosen_profile,
        )

    tokens = load_cached_tokens()
    if tokens:
        return (
            {
                "cookies": cookie_dict(tokens.cookies),
                "csrf_token": tokens.csrf_token or "",
                "session_id": tokens.session_id or "",
                "build_label": tokens.build_label or "",
            },
            "cached_tokens",
        )
    raise RuntimeError(
        "No NotebookLM credentials found. Run `nlm login` first, then retry."
    )


def infer_ext_from_url(url: str, default_ext: str = ".bin") -> str:
    path = unquote(urlparse(url).path or "")
    suffix = Path(path).suffix.lower()
    if suffix and re.fullmatch(r"\.[a-z0-9]{1,6}", suffix):
        return suffix
    return default_ext


def looks_like_image_url(url: str) -> bool:
    return infer_ext_from_url(url, default_ext="").lower() in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
    }


def download_binary(
    url: str,
    out_path: Path,
    cookies: dict[str, str],
    dry_run: bool,
) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme for binary download: {parsed.scheme or '<empty>'}")
    if not parsed.netloc:
        raise ValueError("Binary download URL is missing hostname")

    if dry_run:
        return not out_path.exists()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = {
        "Cookie": cookie_header,
        "Referer": "https://notebooklm.google.com/",
        "User-Agent": "Mozilla/5.0",
    }
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        temp_path = out_path.with_name(f".{out_path.name}.tmp")
        temp_path.write_bytes(resp.content)
        temp_path.replace(out_path)
    return True


def ensure_within_root(root: Path, target: Path) -> None:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if target_resolved == root_resolved or root_resolved not in target_resolved.parents:
        raise RuntimeError(f"Refusing unsafe path operation outside notebook root: {target_resolved}")


def link_line(title: str, rel_path: Path) -> str:
    return f"- [{title}]({rel_path.as_posix()})"


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


def render_note_markdown(
    notebook_id: str,
    notebook_title: str,
    note: dict[str, Any],
    clean_markdown: bool,
) -> str:
    title = str(note.get("title") or "Untitled Note")
    body = str(note.get("content") or "").strip()
    if clean_markdown:
        body = normalize_markdown_body(body)
    return (
        f"---\n"
        f"notebook_id: {notebook_id}\n"
        f"notebook_title: {notebook_title}\n"
        f"note_id: {note.get('id')}\n"
        f"synced_at: {now_iso()}\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"{body}\n"
    )


def render_source_markdown(
    notebook_id: str,
    notebook_title: str,
    source_meta: dict[str, Any],
    source_fulltext: dict[str, Any],
    include_source_content: bool,
    clean_markdown: bool,
) -> str:
    title = str(source_fulltext.get("title") or source_meta.get("title") or "Untitled Source")
    source_id = str(source_meta.get("id") or "")
    source_type_name = str(source_meta.get("source_type_name") or source_fulltext.get("source_type") or "")
    url = str(source_fulltext.get("url") or source_meta.get("url") or "")
    content = str(source_fulltext.get("content") or "").strip()
    body = content if include_source_content else ""
    if not include_source_content:
        body = "_source content skipped (`--include-source-content` to enable)_"
    elif clean_markdown:
        body = normalize_markdown_body(body)
    return (
        f"---\n"
        f"notebook_id: {notebook_id}\n"
        f"notebook_title: {notebook_title}\n"
        f"source_id: {source_id}\n"
        f"source_type: {source_type_name}\n"
        f"url: {url}\n"
        f"status: {source_meta.get('status')}\n"
        f"syncable_drive: {source_meta.get('can_sync')}\n"
        f"char_count: {source_fulltext.get('char_count', 0)}\n"
        f"synced_at: {now_iso()}\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"{body}\n"
    )


def build_notebook_index(
    notebook: Any,
    summary: dict[str, Any],
    note_files: list[tuple[str, Path]],
    source_files: list[tuple[str, Path]],
    photo_files: list[tuple[str, Path]],
) -> str:
    suggested_topics = summary.get("suggested_topics") or []
    topic_lines = "\n".join(
        f"- {topic.get('question', '')}" for topic in suggested_topics if isinstance(topic, dict)
    )
    notes_lines = "\n".join(link_line(title, rel) for title, rel in note_files) or "- _None_"
    sources_lines = "\n".join(link_line(title, rel) for title, rel in source_files) or "- _None_"
    photos_lines = "\n".join(link_line(title, rel) for title, rel in photo_files) or "- _None_"
    return (
        f"# {notebook.title}\n\n"
        f"- Notebook ID: `{notebook.id}`\n"
        f"- Source Count: `{notebook.source_count}`\n"
        f"- Ownership: `{notebook.ownership}`\n"
        f"- Synced At: `{now_iso()}`\n\n"
        f"## Summary\n\n"
        f"{summary.get('summary') or '_No summary available._'}\n\n"
        f"## Suggested Topics\n\n"
        f"{topic_lines or '- _None_'}\n\n"
        f"## Conversations\n\n"
        f"{notes_lines}\n\n"
        f"## Sources\n\n"
        f"{sources_lines}\n\n"
        f"## Photos\n\n"
        f"{photos_lines}\n"
    )


def sync_one_notebook(
    client: NotebookLMClient,
    notebook: Any,
    out_root: Path,
    include_source_content: bool,
    sync_images: bool,
    max_source_chars: int,
    clean_markdown: bool,
    overwrite_notebook: bool,
    notebook_modified_at: str | None,
    sync_profile: dict[str, Any],
    dry_run: bool,
    stats: SyncStats,
    cookies: dict[str, str],
) -> None:
    nb_dir = out_root / f"{sanitize_name(notebook.title)} [{notebook.id[:8]}]"
    conversations_dir = nb_dir / "Conversations"
    sources_dir = nb_dir / "Sources"
    photos_dir = nb_dir / "Photos"
    state_file = nb_dir / ".sync_state.json"

    # Force a full rewrite for this notebook.
    if overwrite_notebook and nb_dir.exists():
        ensure_within_root(out_root, nb_dir)
        if not dry_run:
            shutil.rmtree(nb_dir)

    if not dry_run:
        conversations_dir.mkdir(parents=True, exist_ok=True)
        sources_dir.mkdir(parents=True, exist_ok=True)
        photos_dir.mkdir(parents=True, exist_ok=True)

    prev_state = read_json(state_file, default={})
    new_state = {
        "notes": {},
        "sources": {},
        "photos": {},
        "artifacts": {},
        "notebook_modified_at": notebook_modified_at,
        "sync_profile": sync_profile,
        "synced_at": now_iso(),
    }

    summary = {}
    try:
        summary = client.get_notebook_summary(notebook.id)
    except Exception:
        stats.errors += 1
        summary = {"summary": "", "suggested_topics": []}

    note_files: list[tuple[str, Path]] = []
    source_files: list[tuple[str, Path]] = []
    photo_files: list[tuple[str, Path]] = []

    # Conversations = Notebook Notes
    notes: list[dict[str, Any]] = []
    try:
        notes = client.list_notes(notebook.id)
    except Exception:
        stats.errors += 1
    for note in notes:
        note_id = str(note.get("id") or "")
        note_title = str(note.get("title") or "Untitled Note")
        file_name = f"{sanitize_name(note_title)} [{note_id[:8]}].md"
        out_path = conversations_dir / file_name
        markdown = render_note_markdown(
            notebook.id, notebook.title, note, clean_markdown=clean_markdown
        )
        note_hash = stable_hash(markdown)
        new_state["notes"][note_id] = {"file": file_name, "hash": note_hash}
        changed = write_text_if_changed(out_path, markdown, dry_run)
        if changed:
            stats.notes_written += 1
        else:
            stats.notes_skipped += 1
        note_files.append((note_title, Path("Conversations") / file_name))

    # Sources
    sources = []
    try:
        sources = client.get_notebook_sources_with_types(notebook.id)
    except Exception:
        stats.errors += 1
    for source in sources:
        source_id = str(source.get("id") or "")
        source_title = str(source.get("title") or "Untitled Source")
        fulltext = {
            "content": "",
            "title": source_title,
            "source_type": source.get("source_type_name", ""),
            "url": source.get("url", ""),
            "char_count": 0,
        }
        if include_source_content:
            try:
                fulltext = client.get_source_fulltext(source_id)
            except Exception:
                stats.errors += 1

        content = str(fulltext.get("content") or "")
        if include_source_content and max_source_chars > 0 and len(content) > max_source_chars:
            fulltext["content"] = (
                content[:max_source_chars]
                + "\n\n---\n\n_Truncated by sync script. Increase `--max-source-chars` to keep more._"
            )
            fulltext["char_count"] = len(str(fulltext["content"]))

        source_md = render_source_markdown(
            notebook.id,
            notebook.title,
            source,
            fulltext,
            include_source_content=include_source_content,
            clean_markdown=clean_markdown,
        )
        source_hash = stable_hash(source_md)
        source_file_name = f"{sanitize_name(source_title)} [{source_id[:8]}].md"
        source_path = sources_dir / source_file_name
        new_state["sources"][source_id] = {"file": source_file_name, "hash": source_hash}
        changed = write_text_if_changed(source_path, source_md, dry_run)
        if changed:
            stats.sources_written += 1
        else:
            stats.sources_skipped += 1
        source_files.append((source_title, Path("Sources") / source_file_name))

        # Best-effort image source download
        if sync_images:
            source_url = str(fulltext.get("url") or source.get("url") or "")
            source_type_name = str(source.get("source_type_name") or "").lower()
            if source_url and (source_type_name == "image" or looks_like_image_url(source_url)):
                ext = infer_ext_from_url(source_url, default_ext=".png")
                image_name = f"{sanitize_name(source_title)} [{source_id[:8]}]{ext}"
                image_path = photos_dir / image_name
                photo_key = f"source:{source_id}"
                prev = prev_state.get("photos", {}).get(photo_key, {})
                download_needed = not image_path.exists() or prev.get("url") != source_url
                if download_needed:
                    try:
                        download_binary(source_url, image_path, cookies, dry_run=dry_run)
                        stats.photos_written += 1
                    except Exception:
                        stats.errors += 1
                else:
                    stats.photos_skipped += 1
                new_state["photos"][photo_key] = {"file": image_name, "url": source_url}
                photo_files.append((source_title, Path("Photos") / image_name))

    # Studio infographics -> Photos
    if sync_images:
        try:
            artifacts = client.get_studio_status(notebook.id)
        except Exception:
            artifacts = []
            stats.errors += 1
        for artifact in artifacts:
            if str(artifact.get("type")) != "infographic":
                continue
            artifact_id = str(artifact.get("artifact_id") or "")
            artifact_title = str(artifact.get("title") or "Infographic")
            image_name = f"{sanitize_name(artifact_title)} [{artifact_id[:8]}].png"
            image_path = photos_dir / image_name
            photo_key = f"artifact:{artifact_id}"
            previous = prev_state.get("artifacts", {}).get(artifact_id, {})
            changed = (
                not image_path.exists()
                or previous.get("status") != artifact.get("status")
                or previous.get("created_at") != artifact.get("created_at")
            )
            if changed:
                try:
                    if not dry_run:
                        client.download_infographic(
                            notebook.id,
                            str(image_path),
                            artifact_id=artifact_id,
                        )
                    stats.photos_written += 1
                except Exception:
                    image_url = str(artifact.get("infographic_url") or "")
                    if image_url:
                        try:
                            download_binary(image_url, image_path, cookies, dry_run=dry_run)
                            stats.photos_written += 1
                        except Exception:
                            stats.errors += 1
                    else:
                        stats.errors += 1
            else:
                stats.photos_skipped += 1
            new_state["artifacts"][artifact_id] = {
                "file": image_name,
                "status": artifact.get("status"),
                "created_at": artifact.get("created_at"),
            }
            photo_files.append((artifact_title, Path("Photos") / image_name))

    index_md = build_notebook_index(
        notebook=notebook,
        summary=summary,
        note_files=note_files,
        source_files=source_files,
        photo_files=photo_files,
    )
    write_text_if_changed(nb_dir / "index.md", index_md, dry_run=dry_run)

    if not dry_run:
        write_json(state_file, new_state)
    stats.notebooks_synced += 1


def build_root_index(out_root: Path, notebooks: list[Any], dry_run: bool) -> None:
    lines = [
        "# NotebookLM Sync Index",
        "",
        f"- Generated At: `{now_iso()}`",
        f"- Notebook Count: `{len(notebooks)}`",
        "",
        "## Notebooks",
        "",
    ]
    for nb in notebooks:
        folder = f"{sanitize_name(nb.title)} [{nb.id[:8]}]"
        lines.append(f"- [{nb.title}]({folder}/index.md)")
    lines.append("")
    write_text_if_changed(out_root / "INDEX.md", "\n".join(lines), dry_run=dry_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync NotebookLM notebooks to an Obsidian vault."
    )
    parser.add_argument(
        "--vault-root",
        default=DEFAULT_VAULT_ROOT,
        help=f"Obsidian vault root (default: {DEFAULT_VAULT_ROOT})",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR_NAME,
        help=f"Subdirectory under vault root for sync output (default: {DEFAULT_OUTPUT_DIR_NAME})",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="NotebookLM auth profile name. Uses default profile if omitted.",
    )
    parser.add_argument(
        "--notebook-id",
        action="append",
        default=[],
        help="Only sync this notebook ID (repeatable).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max notebooks to sync (0 means all).",
    )
    parser.add_argument(
        "--include-source-content",
        action="store_true",
        help="Export raw source text into markdown files (slower, larger output).",
    )
    parser.add_argument(
        "--max-source-chars",
        type=int,
        default=120000,
        help="When source content is enabled, truncate each source after this many characters (0 = no truncate).",
    )
    parser.add_argument(
        "--sync-images",
        action="store_true",
        help="Download image sources and infographic artifacts into Photos/.",
    )
    parser.add_argument(
        "--clean-markdown",
        dest="clean_markdown",
        action="store_true",
        default=True,
        help="Normalize exported markdown content for readability (default: enabled).",
    )
    parser.add_argument(
        "--no-clean-markdown",
        dest="clean_markdown",
        action="store_false",
        help="Disable markdown normalization.",
    )
    parser.add_argument(
        "--skip-unchanged-notebooks",
        action="store_true",
        help="Skip a notebook when its NotebookLM modified time is unchanged since last sync.",
    )
    parser.add_argument(
        "--overwrite-changed-notebook",
        action="store_true",
        help="When notebook changed and not skipped, delete and rebuild that notebook folder.",
    )
    parser.add_argument(
        "--overwrite-notebook",
        action="store_true",
        help="Hard overwrite each notebook folder before syncing (delete and rebuild).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    vault_root = Path(args.vault_root).expanduser()
    out_root = vault_root / args.output_dir
    if not vault_root.exists():
        print(f"[ERROR] Vault root does not exist: {vault_root}")
        return 1

    if not args.dry_run:
        out_root.mkdir(parents=True, exist_ok=True)

    try:
        creds, source_name = load_credentials(args.profile)
    except Exception as exc:
        print(f"[ERROR] Failed to load credentials: {exc}")
        return 1

    print(f"[INFO] Credential source: {source_name}")
    stats = SyncStats()
    sync_profile = {
        "include_source_content": bool(args.include_source_content),
        "sync_images": bool(args.sync_images),
        "max_source_chars": int(args.max_source_chars),
        "clean_markdown": bool(args.clean_markdown),
    }

    with NotebookLMClient(
        cookies=creds["cookies"],
        csrf_token=creds["csrf_token"],
        session_id=creds["session_id"],
        build_label=creds["build_label"],
    ) as client:
        notebooks = client.list_notebooks()
        stats.notebooks_seen = len(notebooks)

        if args.notebook_id:
            wanted = {item.strip() for item in args.notebook_id if item.strip()}
            notebooks = [nb for nb in notebooks if nb.id in wanted]

        if args.limit and args.limit > 0:
            notebooks = notebooks[: args.limit]

        print(f"[INFO] Found {stats.notebooks_seen} notebooks, syncing {len(notebooks)}.")
        total_to_sync = len(notebooks)
        for idx, nb in enumerate(notebooks, start=1):
            print(f"[PROGRESS] {idx}/{total_to_sync} {nb.id} {nb.title}")
            nb_dir = out_root / f"{sanitize_name(nb.title)} [{nb.id[:8]}]"
            state_file = nb_dir / ".sync_state.json"
            prev_state = read_json(state_file, default={})
            prev_modified_at = prev_state.get("notebook_modified_at")
            prev_profile = prev_state.get("sync_profile")
            curr_modified_at = getattr(nb, "modified_at", None)
            profile_matches = (prev_profile == sync_profile) or (prev_profile is None)

            if (
                args.skip_unchanged_notebooks
                and nb_dir.exists()
                and curr_modified_at
                and prev_modified_at == curr_modified_at
                and profile_matches
            ):
                stats.notebooks_skipped += 1
                print(f"[SKIP] {nb.title} ({nb.id}) unchanged")
                continue

            # Backward compatibility for older state files: in dry-run mode,
            # if we have a notebook folder but no comparable metadata, assume
            # unchanged to enable fast verification scans without writes.
            if (
                args.skip_unchanged_notebooks
                and args.dry_run
                and nb_dir.exists()
                and not prev_modified_at
            ):
                stats.notebooks_skipped += 1
                print(f"[SKIP] {nb.title} ({nb.id}) assumed unchanged (no prior metadata)")
                continue

            overwrite_this_notebook = bool(args.overwrite_notebook)
            if (
                not overwrite_this_notebook
                and args.overwrite_changed_notebook
                and nb_dir.exists()
                and curr_modified_at
                and prev_modified_at
                and prev_modified_at != curr_modified_at
            ):
                overwrite_this_notebook = True

            print(f"[SYNC] {nb.title} ({nb.id})")
            try:
                sync_one_notebook(
                    client=client,
                    notebook=nb,
                    out_root=out_root,
                    include_source_content=args.include_source_content,
                    sync_images=args.sync_images,
                    max_source_chars=args.max_source_chars,
                    clean_markdown=args.clean_markdown,
                    overwrite_notebook=overwrite_this_notebook,
                    notebook_modified_at=curr_modified_at,
                    sync_profile=sync_profile,
                    dry_run=args.dry_run,
                    stats=stats,
                    cookies=creds["cookies"],
                )
            except Exception as exc:
                stats.errors += 1
                print(f"[WARN] Failed notebook {nb.id}: {exc}")

        build_root_index(out_root=out_root, notebooks=notebooks, dry_run=args.dry_run)

    print("\n[RESULT]")
    print(f"  notebooks_seen:   {stats.notebooks_seen}")
    print(f"  notebooks_synced: {stats.notebooks_synced}")
    print(f"  notebooks_skipped:{stats.notebooks_skipped}")
    print(f"  notes_written:    {stats.notes_written}")
    print(f"  notes_skipped:    {stats.notes_skipped}")
    print(f"  sources_written:  {stats.sources_written}")
    print(f"  sources_skipped:  {stats.sources_skipped}")
    print(f"  photos_written:   {stats.photos_written}")
    print(f"  photos_skipped:   {stats.photos_skipped}")
    print(f"  errors:           {stats.errors}")
    print(f"  output_root:      {out_root}")
    print("[DONE] 100%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
