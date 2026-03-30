#!/usr/bin/env python3
import argparse
import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


SHARE_SEPARATOR = "###------###"
AUTHOR = "HeWei"
DEFAULT_TOPIC_SEGMENT = "89"
TYPE_JS = "CodeType_JAVASCRIPT"
TYPE_MVEL = "CodeType_MVEL"
TAG_JS = "#Javascript"
TAG_MVEL = "#MVEL表达式"
JS_NODE_SUFFIXES = ("ExecuteJS", "MatchJS")
MVEL_NODE_SUFFIXES = ("ExecuteMVEL", "MatchMVEL")
JS_HINT_PATTERNS = (
    r"\bimportClass\s*\(",
    r"\bimportPackage\s*\(",
    r"\bPackages\.",
    r"\bcontext\.",
    r"\bshortx\.",
    r"\bconsole\.log\s*\(",
    r"\bJSON\.stringify\s*\(",
    r"\bvar\s+\w+",
    r"\bfunction\s+\w+\s*\(",
)
MVEL_HINT_PATTERNS = (
    r"\bdef\s+\w+\s*\(",
    r"\bforeach\s*\(",
    r"\blocalVarOf\$",
    r"\bglobalVarOf\$",
    r"\bimport\s+[\w.]+;",
    r"\bString\s+\w+\s*=",
    r"\breturn\s+",
)
DEPENDENCY_PATTERNS = (
    r"(?i)\bDex\b",
    r"(?i)\bJAR\b",
    r"(?i)\.dex\b",
    r"(?i)\.jar\b",
    r"需要\s*Dex",
    r"需要\s*JAR",
    r"依赖\s*Dex",
    r"依赖\s*JAR",
    r"mvnrepository\.com",
    r"PathClassLoader",
)
SAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\r\n]+')
WHITESPACE_RE = re.compile(r"\s+")
HEADER_COMMENT_PREFIXES = ("来源:", "提取自:", "依赖:")
DECORATIVE_COMMENT_RE = re.compile(r"^[=\-_*#~/|·.\s]+$")
LOW_SIGNAL_COMMENT_PATTERNS = (
    re.compile(r"^(true|false)\b", re.IGNORECASE),
    re.compile(r"^(使用示例|工具函数|辅助函数)$"),
    re.compile(r"^(简洁设置入口|执行并返回结果|核心类加载与反射辅助|邮件执行函数|邮件服务器属性配置)$"),
    re.compile(r"^(配置路径|创建\s*loader|加载.+相关类|缓存.+成员|预热.+结构)$"),
    re.compile(r"^配置.+(?:模式|属性配置|等信息)$"),
    re.compile(r"^获取\s+DEFAULT\b"),
    re.compile(r"^获取静态方法\b"),
    re.compile(r"^输出拼音$"),
)
DESCRIPTION_SCAN_NON_EMPTY_LIMIT = 18
ICON_NAME_BY_TYPE = {
    TYPE_JS: "vuejs-line",
    TYPE_MVEL: "code-line",
}
ICON_COLOR_BY_TYPE = {
    TYPE_JS: "#FF9800",
    TYPE_MVEL: "#6750A4",
}


@dataclass
class Sample:
    source_kind: str
    message_id: int
    title: str
    code_type: str
    expression: str
    created_at_text: str
    updated_at_text: str
    created_at_millis: str
    updated_at_millis: str
    dependency_hint: bool
    extraction_note: str | None = None
    sequence: int = 1
    file_label: str | None = None

    @property
    def type_label(self) -> str:
        return "JavaScript" if self.code_type == TYPE_JS else "MVEL"

    @property
    def file_prefix(self) -> str:
        return "JavaScript" if self.code_type == TYPE_JS else "MVEL"

    @property
    def source_link(self) -> str:
        raise RuntimeError("source_link should be assigned before writing")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Telegram chat JS/MVEL samples into ShortX code libraries."
    )
    parser.add_argument("--export-root", required=True, help="Telegram export root directory")
    parser.add_argument("--repo-root", required=True, help="ShortX-Files repository root directory")
    parser.add_argument(
        "--topic-segment",
        default=DEFAULT_TOPIC_SEGMENT,
        help="t.me/c topic segment used in source links",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report without writing files",
    )
    return parser.parse_args()


def load_export(export_root: Path) -> dict:
    result_path = export_root / "result.json"
    return json.loads(result_path.read_text(encoding="utf-8"))


def flatten_text_parts(parts) -> str:
    if isinstance(parts, str):
        return parts
    if not isinstance(parts, list):
        return ""
    output = []
    for part in parts:
        if isinstance(part, str):
            output.append(part)
        elif isinstance(part, dict):
            output.append(part.get("text", ""))
    return "".join(output)


def get_pre_entity(message: dict) -> dict | None:
    for entity in message.get("text_entities") or []:
        if isinstance(entity, dict) and entity.get("type") == "pre":
            return entity
    return None


def get_hashtags(message: dict) -> list[str]:
    return [
        entity.get("text", "")
        for entity in (message.get("text_entities") or [])
        if isinstance(entity, dict) and entity.get("type") == "hashtag"
    ]


def get_parent_title(message: dict, messages_by_id: dict[int, dict]) -> str | None:
    parent_id = message.get("reply_to_message_id")
    seen: set[int] = set()
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent = messages_by_id.get(parent_id)
        if not parent:
            return None
        if parent.get("title"):
            return str(parent["title"]).strip()
        text = flatten_text_parts(parent.get("text"))
        if text.strip():
            return text.strip().splitlines()[0].strip()
        parent_id = parent.get("reply_to_message_id")
    return None


def normalize_title(raw: str | None, fallback: str) -> str:
    title = (raw or "").strip()
    if not title:
        title = fallback
    title = title.replace("\u00a0", " ")
    title = WHITESPACE_RE.sub(" ", title).strip()
    return title or fallback


def sanitize_filename(name: str) -> str:
    name = SAFE_FILENAME_CHARS.sub("_", name)
    name = WHITESPACE_RE.sub(" ", name).strip()
    name = name.replace(".", "．")
    return name[:120].rstrip(" .") or "untitled"


def parse_datetime_millis(value: str) -> str:
    millis = int(datetime.fromisoformat(value).timestamp() * 1000)
    return str(millis)


def parse_message_time_millis(message: dict, unix_key: str, iso_key: str) -> str:
    unix_value = message.get(unix_key)
    if unix_value is not None and str(unix_value).strip():
        return str(int(str(unix_value).strip()) * 1000)
    iso_value = message.get(iso_key)
    if iso_value:
        return parse_datetime_millis(str(iso_value))
    raise ValueError(f"Missing time fields: {unix_key}/{iso_key} for message {message.get('id')}")


def extract_message_timestamps(message: dict) -> tuple[str, str, str, str]:
    created_at_text = str(message.get("date") or "")
    created_at_millis = parse_message_time_millis(message, "date_unixtime", "date")
    has_edit = bool(message.get("edited") or message.get("edited_unixtime"))
    if has_edit:
        updated_at_text = str(message.get("edited") or message.get("date") or "")
        updated_at_millis = parse_message_time_millis(message, "edited_unixtime", "edited")
    else:
        updated_at_text = created_at_text
        updated_at_millis = created_at_millis
    return created_at_text, updated_at_text, created_at_millis, updated_at_millis


def detect_code_type_from_tags_and_text(tags: list[str], text: str) -> str | None:
    if TAG_JS in tags:
        return TYPE_JS
    if TAG_MVEL in tags:
        return TYPE_MVEL
    if any(re.search(pattern, text) for pattern in JS_HINT_PATTERNS):
        return TYPE_JS
    if any(re.search(pattern, text) for pattern in MVEL_HINT_PATTERNS):
        return TYPE_MVEL
    return None


def has_dependency_hint(*texts: str) -> bool:
    joined = "\n".join(text for text in texts if text)
    return any(re.search(pattern, joined) for pattern in DEPENDENCY_PATTERNS)


def is_low_signal_comment(comment: str) -> bool:
    normalized = comment.strip()
    if not normalized:
        return True
    if "===" in normalized:
        return True
    if DECORATIVE_COMMENT_RE.fullmatch(normalized):
        return True
    for pattern in LOW_SIGNAL_COMMENT_PATTERNS:
        if pattern.search(normalized):
            return True
    return False


def clean_block_comment_line(line: str, is_first: bool, is_last: bool) -> str:
    cleaned = line.strip()
    if is_first:
        if cleaned.startswith("/**"):
            cleaned = cleaned[3:]
        elif cleaned.startswith("/*"):
            cleaned = cleaned[2:]
    if is_last and "*/" in cleaned:
        cleaned = cleaned.split("*/", 1)[0]
    cleaned = cleaned.lstrip()
    if cleaned.startswith("*"):
        cleaned = cleaned[1:].lstrip()
    return cleaned.strip()


def normalize_comment_candidate_lines(lines: list[str]) -> str | None:
    normalized_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if any(line.startswith(prefix) for prefix in HEADER_COMMENT_PREFIXES):
            continue
        if is_low_signal_comment(line):
            continue
        normalized_lines.append(line)
    if not normalized_lines:
        return None
    return "\n".join(normalized_lines)


def extract_block_comment(lines: list[str], start_index: int) -> tuple[str | None, int]:
    raw_lines: list[str] = []
    index = start_index
    while index < len(lines):
        stripped = lines[index].strip()
        raw_lines.append(stripped)
        if "*/" in stripped:
            break
        index += 1

    cleaned_lines = [
        clean_block_comment_line(
            line,
            is_first=offset == 0,
            is_last=offset == len(raw_lines) - 1,
        )
        for offset, line in enumerate(raw_lines)
    ]
    return normalize_comment_candidate_lines(cleaned_lines), index


def extract_description(expression: str, fallback: str) -> str:
    lines = expression.splitlines()
    scanned_non_empty = 0
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped:
            scanned_non_empty += 1
        if scanned_non_empty > DESCRIPTION_SCAN_NON_EMPTY_LIMIT:
            break
        if stripped.startswith("/*"):
            block_comment, index = extract_block_comment(lines, index)
            if block_comment:
                return block_comment
            index += 1
            continue
        if stripped.startswith("//"):
            comment = normalize_comment_candidate_lines([stripped[2:].strip()])
            if comment:
                return comment
        index += 1
    return fallback


def build_source_link(chat_id: int, topic_segment: str, message_id: int) -> str:
    return f"https://t.me/c/{chat_id}/{topic_segment}/{message_id}"


def deterministic_code_id(source_key: str) -> str:
    return f"CODELIB-{uuid.uuid5(uuid.NAMESPACE_URL, source_key)}"


def build_content(sample: Sample, source_link: str) -> str:
    header_lines = [f"// 来源: {source_link}"]
    if sample.extraction_note:
        header_lines.append(f"// 提取自: {sample.extraction_note}")
    if sample.dependency_hint:
        header_lines.append("// 依赖: 需要额外 DEX/JAR，详见原消息")
    body = sample.expression.rstrip()
    if body:
        return "\n".join(header_lines) + "\n\n" + body + "\n"
    return "\n".join(header_lines) + "\n"


def code_file_name(sample: Sample) -> str:
    base = sample.file_label or sanitize_filename(sample.title)
    return f"Code-{sample.file_prefix}_{base}.txt"


def sample_sort_key(sample: Sample) -> tuple:
    source_order = 0 if sample.source_kind == "message" else 1
    return (int(sample.created_at_millis), source_order, sample.message_id, sample.sequence)


def collision_suffix(sample: Sample) -> str:
    return "附件" if sample.source_kind == "attachment" else "补充"


def resolve_file_labels(samples: list[Sample]) -> None:
    groups: dict[tuple[str, str], list[Sample]] = defaultdict(list)
    for sample in samples:
        groups[(sample.title, sample.code_type)].append(sample)

    for group in groups.values():
        group.sort(key=sample_sort_key)
        base_name = sanitize_filename(group[0].title)
        if len(group) == 1:
            group[0].file_label = base_name
            continue

        suffix_counts: dict[str, int] = defaultdict(int)
        for index, sample in enumerate(group):
            if index == 0:
                sample.file_label = base_name
                continue
            suffix = collision_suffix(sample)
            suffix_counts[suffix] += 1
            suffix_label = suffix if suffix_counts[suffix] == 1 else f"{suffix}{suffix_counts[suffix]}"
            sample.file_label = f"{base_name}_{suffix_label}"


def collect_message_samples(messages: list[dict], messages_by_id: dict[int, dict]) -> list[Sample]:
    samples: list[Sample] = []
    for message in messages:
        pre = get_pre_entity(message)
        if not pre:
            continue
        expression = pre.get("text", "")
        if not expression.strip():
            continue
        tags = get_hashtags(message)
        code_type = detect_code_type_from_tags_and_text(tags, expression)
        if not code_type:
            continue
        raw_title = pre.get("language") or get_parent_title(message, messages_by_id)
        fallback = f"消息 {message['id']}"
        title = normalize_title(raw_title, fallback)
        dependency_hint = has_dependency_hint(expression, flatten_text_parts(message.get("text")))
        created_at_text, updated_at_text, created_at_millis, updated_at_millis = extract_message_timestamps(message)
        samples.append(
            Sample(
                source_kind="message",
                message_id=message["id"],
                title=title,
                code_type=TYPE_JS if code_type == TYPE_JS else TYPE_MVEL,
                expression=expression,
                created_at_text=created_at_text,
                updated_at_text=updated_at_text,
                created_at_millis=created_at_millis,
                updated_at_millis=updated_at_millis,
                dependency_hint=dependency_hint,
            )
        )
    return samples


def parse_share_body(file_path: Path) -> dict:
    content = file_path.read_text(encoding="utf-8")
    body = content.split(SHARE_SEPARATOR, 1)[0].strip()
    return json.loads(body)


def iter_expression_nodes(node) -> Iterable[tuple[str, str]]:
    if isinstance(node, dict):
        node_type = node.get("@type")
        expression = node.get("expression")
        if isinstance(node_type, str) and isinstance(expression, str):
            suffix = node_type.split("/")[-1]
            if suffix.endswith(JS_NODE_SUFFIXES) or suffix.endswith(MVEL_NODE_SUFFIXES):
                yield suffix, expression
        for value in node.values():
            yield from iter_expression_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_expression_nodes(item)


def node_type_to_code_type(node_type: str) -> str | None:
    if node_type.endswith(JS_NODE_SUFFIXES):
        return TYPE_JS
    if node_type.endswith(MVEL_NODE_SUFFIXES):
        return TYPE_MVEL
    return None


def collect_attachment_samples(
    export_root: Path,
    messages: list[dict],
    messages_by_id: dict[int, dict],
) -> list[Sample]:
    samples: list[Sample] = []
    for message in messages:
        rel_file = message.get("file")
        if not rel_file or not str(rel_file).lower().endswith(".txt"):
            continue
        file_path = export_root / Path(str(rel_file).replace("/", "\\"))
        if not file_path.exists():
            continue
        try:
            share_obj = parse_share_body(file_path)
        except Exception:
            continue
        expressions = list(iter_expression_nodes(share_obj))
        if not expressions:
            continue
        pre = get_pre_entity(message)
        raw_title = (
            share_obj.get("title")
            or share_obj.get("name")
            or (pre.get("language") if pre else None)
            or get_parent_title(message, messages_by_id)
        )
        fallback = Path(message.get("file_name") or file_path.name).stem
        base_title = normalize_title(raw_title, fallback)
        note_file = message.get("file_name") or file_path.name
        note_types = {
            "ExecuteJS": "ExecuteJS",
            "MatchJS": "MatchJS",
            "ExecuteMVEL": "ExecuteMVEL",
            "MatchMVEL": "MatchMVEL",
        }
        message_text = flatten_text_parts(message.get("text"))
        pre_text = pre.get("text", "") if pre else ""
        created_at_text, updated_at_text, created_at_millis, updated_at_millis = extract_message_timestamps(message)
        for index, (node_type, expression) in enumerate(expressions, start=1):
            code_type = node_type_to_code_type(node_type)
            if not code_type:
                continue
            title = base_title
            if len(expressions) > 1:
                title = f"{base_title} [{note_types.get(node_type, node_type)} {index}]"
            dependency_hint = has_dependency_hint(message_text, pre_text, expression)
            samples.append(
                Sample(
                    source_kind="attachment",
                    message_id=message["id"],
                    title=title,
                    code_type=code_type,
                    expression=expression,
                    created_at_text=created_at_text,
                    updated_at_text=updated_at_text,
                    created_at_millis=created_at_millis,
                    updated_at_millis=updated_at_millis,
                    dependency_hint=dependency_hint,
                    extraction_note=f"{note_file} ({note_types.get(node_type, node_type)})",
                    sequence=index,
                )
            )
    return samples


def write_code_library(repo_root: Path, chat_id: int, topic_segment: str, sample: Sample) -> Path:
    code_dir = repo_root / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    source_link = build_source_link(chat_id, topic_segment, sample.message_id)
    content = build_content(sample, source_link)
    payload = {
        "id": deterministic_code_id(f"{sample.source_kind}:{sample.message_id}:{sample.sequence}:{sample.title}:{sample.code_type}"),
        "name": sample.title,
        "description": extract_description(sample.expression, sample.title),
        "type": sample.code_type,
        "content": content,
        "createdAt": sample.created_at_millis,
        "updatedAt": sample.updated_at_millis,
        "tags": [
            "example",
            "telegram",
            "javascript" if sample.code_type == TYPE_JS else "mvel",
        ],
    }
    file_name = code_file_name(sample)
    target = code_dir / file_name
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n"
        + SHARE_SEPARATOR
        + "\n"
        + json.dumps({"type": "CodeLibraryItem", "author": AUTHOR}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return target


def parse_code_library_file(file_path: Path) -> tuple[dict, dict]:
    text = file_path.read_text(encoding="utf-8")
    parts = text.strip().split(SHARE_SEPARATOR, 1)
    body = json.loads(parts[0].strip())
    header = {}
    if len(parts) > 1 and parts[1].strip():
        header = json.loads(parts[1].strip())
    return body, header


def remove_code_library_files_by_author(repo_root: Path, author: str) -> int:
    code_dir = repo_root / "code"
    removed = 0
    for file_path in code_dir.glob("Code-*.txt"):
        try:
            _, header = parse_code_library_file(file_path)
        except Exception:
            continue
        if (header.get("author") or "").strip() == author:
            file_path.unlink()
            removed += 1
    return removed


def build_code_library_index_items(repo_root: Path) -> list[dict]:
    code_dir = repo_root / "code"
    items: list[dict] = []
    for file_path in sorted(code_dir.glob("*.txt"), key=lambda path: path.name.lower()):
        body, header = parse_code_library_file(file_path)
        code_type = body["type"]
        items.append(
            {
                "id": body["id"],
                "fileUrl": file_path.name,
                "title": body["name"],
                "description": body.get("description", ""),
                "versionCode": 1,
                "updateTimeMillis": int(body["updatedAt"]),
                "author": (header.get("author") or "").strip() or "ShortX",
                "tags": body.get("tags", []),
                "icon": ICON_NAME_BY_TYPE.get(code_type, "code-line"),
                "iconColor": ICON_COLOR_BY_TYPE.get(code_type, "#607D8B"),
                "requireMinShortXProtoVersion": 0,
            }
        )
    return items


def update_index_json(repo_root: Path) -> None:
    index_path = repo_root / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {}
    code_libraries = build_code_library_index_items(repo_root)
    index["directActions"] = index.get("directActions", [])
    index["rules"] = index.get("rules", [])
    index["codeLibraries"] = code_libraries
    all_items = index["directActions"] + index["rules"] + code_libraries
    index["updateTimeMillis"] = max(
        (int(item.get("updateTimeMillis", 0)) for item in all_items),
        default=0,
    )
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    export_root = Path(args.export_root)
    repo_root = Path(args.repo_root)
    data = load_export(export_root)
    messages = data["messages"]
    chat_id = int(data["id"])
    messages_by_id = {message["id"]: message for message in messages}

    message_samples = collect_message_samples(messages, messages_by_id)
    attachment_samples = collect_attachment_samples(export_root, messages, messages_by_id)
    all_samples = message_samples + attachment_samples
    resolve_file_labels(all_samples)

    if args.dry_run:
        collision_groups = sum(
            1
            for samples_in_group in defaultdict(
                list,
                {
                    (sample.title, sample.code_type): [
                        grouped for grouped in all_samples
                        if grouped.title == sample.title and grouped.code_type == sample.code_type
                    ]
                    for sample in all_samples
                },
            ).values()
            if len(samples_in_group) > 1
        )
        summary = {
            "message_samples": len(message_samples),
            "attachment_samples": len(attachment_samples),
            "total_samples": len(all_samples),
            "collision_groups": collision_groups,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    removed_files = remove_code_library_files_by_author(repo_root, AUTHOR)
    written_files = []
    for sample in all_samples:
        written_files.append(write_code_library(repo_root, chat_id, args.topic_segment, sample))

    update_index_json(repo_root)

    print(
        json.dumps(
            {
                "message_samples": len(message_samples),
                "attachment_samples": len(attachment_samples),
                "total_samples": len(all_samples),
                "removed_files": removed_files,
                "written_files": len(written_files),
                "index_updated": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
