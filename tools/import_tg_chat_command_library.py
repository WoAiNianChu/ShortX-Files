#!/usr/bin/env python3
import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


SHARE_SEPARATOR = "###------###"
SHARE_TYPE_DA = "da"
SHARE_TYPE_RULE = "rule"
SHARE_TYPE_CODE_LIBRARY = "codelibraryitem"
SAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\r\n]+')
WHITESPACE_RE = re.compile(r"\s+")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")
VERSION_LINE_PATTERNS = (
    re.compile(r"(?i)\bversion\s*([0-9]+(?:\.[0-9]+){1,3})"),
    re.compile(r"([0-9]+(?:\.[0-9]+){1,3})\s*版本"),
)
VERSION_NAME_PATTERNS = (
    re.compile(r"(?i)[_\s-]v([0-9]+(?:\.[0-9]+){1,3})$"),
    re.compile(r"[_\s-]([0-9]+(?:\.[0-9]+){1,3})$"),
    re.compile(r"(?i)[(（]v?([0-9]+(?:\.[0-9]+){1,3})[)）]?$"),
    re.compile(r"(?i)[(（]v?([0-9]+(?:\.[0-9]+){1,3})$"),
)


@dataclass(frozen=True)
class ShareItem:
    share_type: str
    project_id: str
    title: str
    description: str
    source_name: str
    raw_content: str
    body: dict
    message_id: int | None
    origin: str
    repo_path: Path | None = None
    archive_dir_name: str | None = None
    version_code: int = -1
    last_update_time: int = -1
    version_label: str | None = None
    version_tuple: tuple[int, int, int, int] | None = None
    has_explicit_version_name: bool = False

    @property
    def target_subdir(self) -> str:
        return "da" if self.share_type == SHARE_TYPE_DA else "rule"

    @property
    def identity_key(self) -> tuple[str, str, str]:
        return (self.share_type, self.project_id, self.raw_content)


@dataclass(frozen=True)
class RepoProjectState:
    existing_paths: tuple[Path, ...]
    archive_dir_name: str | None


@dataclass(frozen=True)
class PlannedProject:
    share_type: str
    project_id: str
    archive_dir_name: str | None
    latest_root_path: Path
    latest_item: ShareItem
    archive_items: tuple[tuple[Path, ShareItem], ...]
    obsolete_paths: tuple[Path, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Telegram chat direct actions/rules into ShortX command libraries."
    )
    parser.add_argument("--export-root", required=True, help="Telegram export root directory")
    parser.add_argument("--repo-root", required=True, help="ShortX-Files repository root directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report without writing files",
    )
    return parser.parse_args()


def load_export(export_root: Path) -> dict:
    result_path = export_root / "result.json"
    return json.loads(result_path.read_text(encoding="utf-8"))


def parse_int(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


def contains_han(text: str) -> bool:
    return bool(HAN_RE.search(text or ""))


def sanitize_shared_filename(name: str, fallback: str) -> str:
    sanitized = SAFE_FILENAME_CHARS.sub("_", name or "")
    sanitized = WHITESPACE_RE.sub(" ", sanitized).strip()
    if not sanitized:
        sanitized = fallback
    if not sanitized.lower().endswith(".txt"):
        sanitized += ".txt"
    return sanitized[:160].rstrip(" .") or f"{fallback}.txt"


def sanitize_directory_name(name: str, fallback: str) -> str:
    sanitized = SAFE_FILENAME_CHARS.sub("_", name or "")
    sanitized = WHITESPACE_RE.sub(" ", sanitized).strip(" ._")
    return sanitized[:120].rstrip(" .") or fallback


def normalize_share_type(raw_type: object) -> str | None:
    if not isinstance(raw_type, str):
        return None
    lowered = raw_type.strip().lower()
    if lowered == SHARE_TYPE_DA:
        return SHARE_TYPE_DA
    if lowered == SHARE_TYPE_RULE:
        return SHARE_TYPE_RULE
    if lowered == SHARE_TYPE_CODE_LIBRARY:
        return SHARE_TYPE_CODE_LIBRARY
    return None


def parse_share_file(file_path: Path) -> tuple[str, dict, dict]:
    raw_content = file_path.read_text(encoding="utf-8")
    parts = raw_content.split(SHARE_SEPARATOR, 1)
    body = json.loads(parts[0].strip())
    header = json.loads(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else {}
    return raw_content, body, header


def is_valid_direct_action(body: dict) -> bool:
    return (
        isinstance(body, dict)
        and isinstance(body.get("id"), str)
        and isinstance(body.get("title"), str)
        and isinstance(body.get("actions"), list)
    )


def is_valid_rule(body: dict) -> bool:
    if not (
        isinstance(body, dict)
        and isinstance(body.get("id"), str)
        and isinstance(body.get("title"), str)
    ):
        return False
    return any(isinstance(body.get(key), list) for key in ("facts", "conditions", "actions"))


def normalize_version_label(label: str) -> tuple[str, tuple[int, int, int, int]]:
    parts = [int(part) for part in label.split(".") if part.strip()]
    padded = tuple((parts + [0, 0, 0, 0])[:4])
    normalized = ".".join(str(part) for part in parts)
    return normalized, padded


def detect_version_in_name(text: str) -> tuple[str | None, tuple[int, int, int, int] | None]:
    stem = Path(text).stem.strip() if text.lower().endswith(".txt") else text.strip()
    for pattern in VERSION_NAME_PATTERNS:
        match = pattern.search(stem)
        if match:
            return normalize_version_label(match.group(1))
    return None, None


def detect_version_in_description(text: str) -> tuple[str | None, tuple[int, int, int, int] | None]:
    if not text:
        return None, None
    non_empty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in non_empty_lines[:6]:
        for pattern in VERSION_LINE_PATTERNS:
            match = pattern.search(line)
            if match:
                return normalize_version_label(match.group(1))
    return None, None


def derive_project_name(title: str, source_name: str) -> str:
    candidates = [title.strip(), Path(source_name).stem.strip()]
    for candidate in candidates:
        if candidate.lower().startswith("shortx-"):
            candidate = candidate[7:].strip()
        stripped = candidate
        for pattern in VERSION_NAME_PATTERNS:
            stripped = pattern.sub("", stripped).strip(" _-()（）")
        stripped = stripped.strip()
        if stripped:
            return sanitize_directory_name(stripped, "project")
    return "project"


def build_share_item(
    *,
    share_type: str,
    body: dict,
    raw_content: str,
    source_name: str,
    message_id: int | None,
    origin: str,
    repo_path: Path | None = None,
    archive_dir_name: str | None = None,
) -> ShareItem:
    title = str(body.get("title") or "").strip()
    description = str(body.get("description") or "")
    version_label, version_tuple = detect_version_in_name(source_name)
    has_explicit_version_name = version_label is not None
    if version_label is None:
        version_label, version_tuple = detect_version_in_name(title)
    if version_label is None:
        version_label, version_tuple = detect_version_in_description(description)
    return ShareItem(
        share_type=share_type,
        project_id=str(body["id"]).strip(),
        title=title,
        description=description,
        source_name=source_name,
        raw_content=raw_content if raw_content.endswith("\n") else raw_content + "\n",
        body=body,
        message_id=message_id,
        origin=origin,
        repo_path=repo_path,
        archive_dir_name=archive_dir_name,
        version_code=parse_int(body.get("versionCode")),
        last_update_time=parse_int(body.get("lastUpdateTime")),
        version_label=version_label,
        version_tuple=version_tuple,
        has_explicit_version_name=has_explicit_version_name,
    )


def is_chinese_preferred(item: ShareItem) -> bool:
    return contains_han(item.title) or contains_han(item.source_name)


def collect_attachment_candidates(export_root: Path, messages: list[dict]) -> tuple[list[ShareItem], dict]:
    stats = {
        "attachments_seen": 0,
        "importable_candidates": 0,
        "direct_actions": 0,
        "rules": 0,
        "skipped_missing_file": 0,
        "skipped_invalid_json": 0,
        "skipped_code_libraries": 0,
        "skipped_unknown_type": 0,
        "skipped_invalid_shape": 0,
    }
    candidates: list[ShareItem] = []

    for message in messages:
        rel_file = message.get("file")
        if not rel_file or not str(rel_file).lower().endswith(".txt"):
            continue
        stats["attachments_seen"] += 1
        file_path = export_root / Path(str(rel_file).replace("/", "\\"))
        if not file_path.exists():
            stats["skipped_missing_file"] += 1
            continue
        try:
            raw_content, body, header = parse_share_file(file_path)
        except Exception:
            stats["skipped_invalid_json"] += 1
            continue

        share_type = normalize_share_type(header.get("type"))
        if share_type == SHARE_TYPE_CODE_LIBRARY:
            stats["skipped_code_libraries"] += 1
            continue
        if share_type is None:
            stats["skipped_unknown_type"] += 1
            continue

        is_valid = is_valid_direct_action(body) if share_type == SHARE_TYPE_DA else is_valid_rule(body)
        if not is_valid:
            stats["skipped_invalid_shape"] += 1
            continue

        source_name = sanitize_shared_filename(
            str(message.get("file_name") or file_path.name),
            fallback=f"message_{message.get('id', 'unknown')}",
        )
        candidates.append(
            build_share_item(
                share_type=share_type,
                body=body,
                raw_content=raw_content,
                source_name=source_name,
                message_id=int(message["id"]),
                origin="import",
            )
        )
        stats["importable_candidates"] += 1
        if share_type == SHARE_TYPE_DA:
            stats["direct_actions"] += 1
        else:
            stats["rules"] += 1

    return candidates, stats


def scan_repo_share_items(repo_root: Path, project_keys: set[tuple[str, str]]) -> dict[tuple[str, str], list[ShareItem]]:
    by_project: dict[tuple[str, str], list[ShareItem]] = defaultdict(list)
    for share_type in (SHARE_TYPE_DA, SHARE_TYPE_RULE):
        base_dir = repo_root / ("da" if share_type == SHARE_TYPE_DA else "rule")
        if not base_dir.exists():
            continue
        for path in base_dir.rglob("*.txt"):
            try:
                raw_content, body, header = parse_share_file(path)
            except Exception:
                continue
            if normalize_share_type(header.get("type")) != share_type:
                continue
            project_id = str(body.get("id") or "").strip()
            if not project_id:
                continue
            project_key = (share_type, project_id)
            if project_key not in project_keys:
                continue
            archive_dir_name = None
            if path.parent != base_dir:
                archive_dir_name = path.parent.name
            by_project[project_key].append(
                build_share_item(
                    share_type=share_type,
                    body=body,
                    raw_content=raw_content,
                    source_name=sanitize_shared_filename(path.name, path.stem or "repo_item"),
                    message_id=None,
                    origin="repo",
                    repo_path=path,
                    archive_dir_name=archive_dir_name,
                )
            )
    return by_project


def item_rank(item: ShareItem) -> tuple[int, tuple[int, int, int, int], int, int, int]:
    return (
        item.version_code,
        item.version_tuple or (0, 0, 0, 0),
        1 if is_chinese_preferred(item) else 0,
        item.last_update_time,
        1 if item.origin == "import" else 0,
        item.message_id or -1,
    )


def choose_better_item(current: ShareItem | None, candidate: ShareItem) -> ShareItem:
    if current is None:
        return candidate
    return candidate if item_rank(candidate) >= item_rank(current) else current


def dedupe_existing_items(imported_items: list[ShareItem], existing_items: list[ShareItem]) -> list[ShareItem]:
    imported_raw_contents = {item.raw_content for item in imported_items}
    filtered: list[ShareItem] = []
    for item in existing_items:
        if item.raw_content in imported_raw_contents:
            continue
        filtered.append(item)
    return filtered


def resolve_archive_dir_name(project_items: list[ShareItem]) -> str | None:
    preferred_name_item = max(project_items, key=item_rank)
    preferred_name = derive_project_name(preferred_name_item.title, preferred_name_item.source_name)
    existing_names = [item.archive_dir_name for item in project_items if item.archive_dir_name]
    if len(project_items) <= 1 and not existing_names:
        return None
    if contains_han(preferred_name):
        return preferred_name
    if existing_names:
        return sorted(existing_names, key=lambda name: (-existing_names.count(name), name))[0]
    return preferred_name


def build_versioned_archive_name(project_name: str, item: ShareItem) -> str:
    stem = project_name
    version_token = item.version_label
    if version_token:
        return sanitize_shared_filename(f"ShortX-{stem}_{version_token}.txt", fallback=f"{stem}.txt")
    if item.version_code >= 0:
        return sanitize_shared_filename(f"ShortX-{stem}_vc{item.version_code}.txt", fallback=f"{stem}.txt")
    if item.message_id is not None:
        return sanitize_shared_filename(f"ShortX-{stem}_m{item.message_id}.txt", fallback=f"{stem}.txt")
    return sanitize_shared_filename(f"ShortX-{stem}_{item.last_update_time}.txt", fallback=f"{stem}.txt")


def plan_archive_items(project_items: list[ShareItem], project_name: str) -> dict[str, ShareItem]:
    archive_map: dict[str, ShareItem] = {}
    items_by_source_name: dict[str, list[ShareItem]] = defaultdict(list)
    for item in project_items:
        items_by_source_name[item.source_name].append(item)

    for source_name, items in items_by_source_name.items():
        unique_items_by_content: dict[str, ShareItem] = {}
        for item in items:
            unique_items_by_content[item.raw_content] = choose_better_item(unique_items_by_content.get(item.raw_content), item)
        unique_items = list(unique_items_by_content.values())

        if len(unique_items) == 1:
            archive_map[source_name] = choose_better_item(archive_map.get(source_name), unique_items[0])
            continue

        has_explicit = any(item.has_explicit_version_name for item in unique_items)
        if has_explicit:
            best = max(unique_items, key=item_rank)
            archive_map[source_name] = choose_better_item(archive_map.get(source_name), best)
            continue

        for item in unique_items:
            versioned_name = build_versioned_archive_name(project_name, item)
            archive_map[versioned_name] = choose_better_item(archive_map.get(versioned_name), item)

    return archive_map


def plan_projects(repo_root: Path, imported_items: list[ShareItem]) -> tuple[list[PlannedProject], dict]:
    imported_by_project: dict[tuple[str, str], list[ShareItem]] = defaultdict(list)
    for item in imported_items:
        imported_by_project[(item.share_type, item.project_id)].append(item)

    existing_by_project = scan_repo_share_items(repo_root, set(imported_by_project.keys()))

    planned_projects: list[PlannedProject] = []
    total_archive_files = 0
    removed_paths = 0

    for project_key, imported_group in imported_by_project.items():
        share_type, project_id = project_key
        existing_group = dedupe_existing_items(imported_group, existing_by_project.get(project_key, []))
        project_items = imported_group + existing_group
        latest_item = max(project_items, key=item_rank)
        archive_dir_name = resolve_archive_dir_name(project_items)

        target_base_dir = repo_root / ("da" if share_type == SHARE_TYPE_DA else "rule")
        archive_items_map: dict[str, ShareItem] = {}
        if archive_dir_name:
            archive_items_map = plan_archive_items(project_items, archive_dir_name)

        archive_items = tuple(
            sorted(
                (
                    (target_base_dir / archive_dir_name / archive_name, item)
                    for archive_name, item in archive_items_map.items()
                ),
                key=lambda pair: pair[0].name.lower(),
            )
        )
        latest_root_path = target_base_dir / latest_item.source_name

        desired_paths = {latest_root_path, *(path for path, _ in archive_items)}
        existing_paths = tuple(item.repo_path for item in existing_by_project.get(project_key, []) if item.repo_path)
        obsolete_paths = tuple(sorted((path for path in existing_paths if path not in desired_paths), key=lambda path: str(path).lower()))
        total_archive_files += len(archive_items)
        removed_paths += len(obsolete_paths)

        planned_projects.append(
            PlannedProject(
                share_type=share_type,
                project_id=project_id,
                archive_dir_name=archive_dir_name,
                latest_root_path=latest_root_path,
                latest_item=latest_item,
                archive_items=archive_items,
                obsolete_paths=obsolete_paths,
            )
        )

    summary = {
        "planned_projects": len(planned_projects),
        "planned_direct_action_projects": sum(1 for project in planned_projects if project.share_type == SHARE_TYPE_DA),
        "planned_rule_projects": sum(1 for project in planned_projects if project.share_type == SHARE_TYPE_RULE),
        "planned_archive_files": total_archive_files,
        "obsolete_paths": removed_paths,
    }
    return planned_projects, summary


def execute_plans(planned_projects: list[PlannedProject]) -> dict:
    written_files = 0
    deleted_paths = 0
    created_dirs: set[Path] = set()
    cleanup_dirs: set[Path] = set()

    for project in planned_projects:
        if project.archive_dir_name:
            archive_dir = project.latest_root_path.parent / project.archive_dir_name
            archive_dir.mkdir(parents=True, exist_ok=True)
            created_dirs.add(archive_dir)

        for path in project.obsolete_paths:
            if path.exists():
                cleanup_dirs.add(path.parent)
                path.unlink()
                deleted_paths += 1

        project.latest_root_path.parent.mkdir(parents=True, exist_ok=True)
        project.latest_root_path.write_text(project.latest_item.raw_content, encoding="utf-8")
        written_files += 1

        for archive_path, archive_item in project.archive_items:
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            archive_path.write_text(archive_item.raw_content, encoding="utf-8")
            written_files += 1

        if project.archive_dir_name:
            archive_dir = project.latest_root_path.parent / project.archive_dir_name
            if archive_dir.exists() and not any(archive_dir.iterdir()):
                archive_dir.rmdir()

    for directory in sorted(cleanup_dirs, key=lambda path: len(path.parts), reverse=True):
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()

    return {
        "written_files": written_files,
        "deleted_paths": deleted_paths,
    }


def summarize_plan(planned_projects: list[PlannedProject], collect_stats: dict, plan_stats: dict) -> dict:
    items = []
    for project in sorted(planned_projects, key=lambda item: (item.share_type, item.latest_root_path.name.lower())):
        items.append(
            {
                "type": project.share_type,
                "project_id": project.project_id,
                "archive_dir_name": project.archive_dir_name,
                "latest_root_path": str(project.latest_root_path),
                "latest_root_file": project.latest_root_path.name,
                "latest_version_code": project.latest_item.version_code,
                "latest_version_label": project.latest_item.version_label,
                "archive_files": [str(path) for path, _ in project.archive_items],
                "obsolete_paths": [str(path) for path in project.obsolete_paths],
            }
        )
    return {
        **collect_stats,
        **plan_stats,
        "items": items,
    }


def main() -> None:
    args = parse_args()
    export_root = Path(args.export_root)
    repo_root = Path(args.repo_root)

    data = load_export(export_root)
    imported_items, collect_stats = collect_attachment_candidates(export_root, data["messages"])
    planned_projects, plan_stats = plan_projects(repo_root, imported_items)
    summary = summarize_plan(planned_projects, collect_stats, plan_stats)

    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    write_stats = execute_plans(planned_projects)
    print(json.dumps({**summary, **write_stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
