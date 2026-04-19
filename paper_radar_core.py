from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import os
import re
import shlex
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import requests

try:
    import yaml
except ModuleNotFoundError:
    yaml = None


ARXIV_API = "https://export.arxiv.org/api/query"
OPENREVIEW_API = "https://api2.openreview.net/notes"
OPENALEX_WORKS_API = "https://api.openalex.org/works"
OPENALEX_RATE_LIMIT_API = "https://api.openalex.org/rate-limit"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"

DEFAULT_CONFIG_DIR = Path("configs")
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "robotics.yaml"
DEFAULT_PRESET_DIR = Path("data/gui_presets")
DEFAULT_WARNING_LOG_PATH = Path("data/runtime_warnings.log")
DEFAULT_DB_PATH = Path("data/paper_radar.sqlite3")

WEIGHT_KEYS = (
    "relevance",
    "novelty",
    "empirical",
    "source_signal",
    "momentum",
    "recency",
    "actionability",
)
BUCKET_KEYS = ("must_read", "worth_reading", "skim")
TRACK_UNASSIGNED = "unassigned"
SOURCE_PRIORITY = {"openreview": 4, "arxiv": 3, "openalex": 2, "semanticscholar": 1}
OPENALEX_AFFILIATION_CATALOG_KIND = "openalex_affiliation_catalog"
OPENALEX_PRIORITY_BONUS = 25.0

BUILTIN_TRACK_DEFINITIONS: dict[str, dict[str, Any]] = {
    "vla": {
        "label": "VLA",
        "keywords": [
            "vision-language-action",
            "vla",
            "vlm policy",
            "multimodal policy",
            "instruction-conditioned control",
        ],
    },
    "manipulation": {
        "label": "Manipulation",
        "keywords": [
            "manipulation",
            "grasp",
            "dexterous",
            "bimanual",
            "contact-rich",
            "in-hand",
        ],
    },
    "humanoid": {
        "label": "Humanoid",
        "keywords": [
            "humanoid",
            "whole-body",
            "locomotion",
            "walking",
            "upper-body",
            "teleoperation",
        ],
    },
    "world_model": {
        "label": "World Model",
        "keywords": [
            "world model",
            "predictive control",
            "latent dynamics",
            "model-based policy",
            "planning",
            "visuomotor world model",
        ],
    },
    "supporting_ml": {
        "label": "Supporting ML",
        "keywords": [
            "data curation",
            "representation learning",
            "foundation model",
            "benchmark",
            "dataset",
            "sim2real",
        ],
    },
    "ml_theory": {
        "label": "ML Theory",
        "keywords": [
            "generalization",
            "optimization",
            "convergence",
            "sample complexity",
            "pac-bayes",
            "theory",
        ],
    },
    "llm_foundations": {
        "label": "LLM Foundations",
        "keywords": [
            "large language model",
            "llm",
            "transformer theory",
            "in-context learning",
            "mechanistic interpretability",
        ],
    },
    "data_and_curation": {
        "label": "Data And Curation",
        "keywords": [
            "data curation",
            "data filtering",
            "data mixture",
            "synthetic data",
            "contamination",
            "deduplication",
        ],
    },
    "scaling_and_pretraining": {
        "label": "Scaling And Pretraining",
        "keywords": [
            "scaling law",
            "pretraining",
            "curriculum learning",
            "tokenization",
            "training dynamics",
        ],
    },
    "representation_learning": {
        "label": "Representation Learning",
        "keywords": [
            "representation learning",
            "self-supervised",
            "contrastive",
            "masked modeling",
            "embedding",
        ],
    },
    "alignment_and_posttraining": {
        "label": "Alignment And Post-training",
        "keywords": [
            "alignment",
            "post-training",
            "rlhf",
            "dpo",
            "reward model",
            "verifier",
        ],
    },
}

@dataclass
class Paper:
    source: str
    external_id: str
    title: str
    abstract: str
    authors: list[str]
    published_at: str | None
    updated_at: str | None
    url: str
    pdf_url: str | None
    venue: str | None = None
    categories: list[str] = field(default_factory=list)
    doi: str | None = None
    citations: int | None = None
    topics: list[str] = field(default_factory=list)
    decision: str | None = None
    review_signal: float | None = None
    review_count: int = 0
    canonical_id: str | None = None
    track_ids: list[str] = field(default_factory=list)
    primary_track: str | None = None
    track_reasons: dict[str, list[str]] = field(default_factory=dict)
    source_metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    # harness-generated fields
    normalized_title: str | None = None
    relevance_score: float = 0.0
    novelty_score: float = 0.0
    empirical_score: float = 0.0
    source_signal_score: float = 0.0
    momentum_score: float = 0.0
    recency_score: float = 0.0
    actionability_score: float = 0.0
    final_score: float = 0.0
    bucket: str | None = None


@dataclass
class FetchOptions:
    queries: list[str]
    categories: list[str]
    days_back: int
    max_results_per_query: int
    enable_semanticscholar: bool
    semanticscholar_api_key_env: str = "SEMANTIC_SCHOLAR_API_KEY"
    enable_openreview: bool = False
    openreview_venues: list[str] = field(default_factory=list)
    openreview_keywords: list[str] = field(default_factory=list)
    enable_openalex: bool = False
    openalex_api_key_env: str = "OPENALEX_API_KEY"


@dataclass
class RankOptions:
    include_keywords: list[str]
    exclude_keywords: list[str]
    weights: dict[str, float]
    buckets: dict[str, float]
    daily_top_k: int
    openalex_priority_catalogs: list[str] = field(default_factory=list)


@dataclass
class OpenAlexAffiliationEntity:
    key: str
    label: str
    aliases: list[str] = field(default_factory=list)
    openalex_ids: list[str] = field(default_factory=list)
    normalized_aliases: set[str] = field(default_factory=set)
    normalized_openalex_ids: set[str] = field(default_factory=set)


@dataclass
class OpenAlexAffiliationCatalog:
    path: str
    catalog_name: str
    entities: dict[str, OpenAlexAffiliationEntity]


@dataclass
class DigestOptions:
    daily_top_k: int
    weekly_top_k_per_track: int
    tracks: list[str]
    track_definitions: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class TrackDigest:
    daily_markdown: str
    weekly_markdown: str
    daily_sections: list[dict[str, Any]]
    weekly_sections: list[dict[str, Any]]


@dataclass
class RunExecution:
    run_id: int | None
    config_hash: str
    fetch_signature: str
    raw_papers: list[Paper]
    ranked_papers: list[Paper]
    source_status: dict[str, Any]
    daily_digest: str
    weekly_digest: str


def get_config_path(
    argv: list[str] | None = None,
    default_path: str | Path = DEFAULT_CONFIG_PATH,
) -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("config_path", nargs="?")
    parser.add_argument("--config-path", dest="config_path_flag")
    args, _ = parser.parse_known_args(argv)

    raw_path = args.config_path_flag or args.config_path or os.getenv("PAPER_RADAR_CONFIG")
    candidate = Path(raw_path).expanduser() if raw_path else Path(default_path)
    return resolve_config_path(candidate)


def resolve_config_path(path: str | Path, *, config_dir: str | Path = DEFAULT_CONFIG_DIR) -> Path:
    candidate = Path(path).expanduser()
    if candidate.exists():
        return candidate

    config_root = Path(config_dir).expanduser()
    fallback = config_root / candidate.name
    if not candidate.is_absolute() and len(candidate.parts) == 1 and fallback.exists():
        return fallback

    legacy_prefix = "paper_radar_config_"
    if candidate.name.startswith(legacy_prefix):
        stripped_name = candidate.name[len(legacy_prefix) :]
        stripped_candidate = candidate.with_name(stripped_name)
        if stripped_candidate.exists():
            return stripped_candidate
        stripped_fallback = config_root / stripped_name
        if stripped_fallback.exists():
            return stripped_fallback

    raise FileNotFoundError(f"Config file not found: {candidate}")


def load_config(path: str | Path) -> dict[str, Any]:
    resolved = resolve_config_path(path)
    with open(resolved, "r", encoding="utf-8") as f:
        text = f.read()
    if yaml is not None:
        return yaml.safe_load(text)
    return _load_simple_yaml(text)


def save_config(path: str | Path, config: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to save config files.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)


def is_openalex_affiliation_catalog_config(config: Mapping[str, Any]) -> bool:
    return str(config.get("kind") or "").strip() == OPENALEX_AFFILIATION_CATALOG_KIND


def load_openalex_affiliation_catalog(path: str | Path) -> OpenAlexAffiliationCatalog:
    resolved = resolve_config_path(path)
    payload = load_config(resolved)
    if not is_openalex_affiliation_catalog_config(payload):
        raise ValueError(f"{resolved} is not an {OPENALEX_AFFILIATION_CATALOG_KIND} file.")

    catalog_name = str(payload.get("catalog_name") or resolved.stem).strip()
    entities_cfg = payload.get("entities")
    if not isinstance(entities_cfg, Mapping) or not entities_cfg:
        raise ValueError(f"{resolved} does not define any catalog entities.")

    entities: dict[str, OpenAlexAffiliationEntity] = {}
    for entity_key, entity_value in entities_cfg.items():
        if not isinstance(entity_value, Mapping):
            raise ValueError(f"{resolved} has an invalid entity entry for {entity_key!r}.")
        key = str(entity_key).strip()
        label = str(entity_value.get("label") or key).strip()
        aliases_cfg = entity_value.get("aliases", [])
        if isinstance(aliases_cfg, str):
            aliases_cfg = [aliases_cfg]
        ids_cfg = entity_value.get("openalex_ids", [])
        if isinstance(ids_cfg, str):
            ids_cfg = [ids_cfg]
        aliases = [str(item).strip() for item in aliases_cfg if str(item).strip()]
        openalex_ids = [
            normalized_id
            for normalized_id in (
                normalize_openalex_id(item) for item in ids_cfg
            )
            if normalized_id
        ]
        normalized_aliases = {
            normalized
            for normalized in (
                normalize_affiliation_name(name) for name in [label, *aliases]
            )
            if normalized
        }
        if not normalized_aliases and not openalex_ids:
            raise ValueError(f"{resolved} entity {key!r} has no usable aliases or OpenAlex ids.")
        entities[key] = OpenAlexAffiliationEntity(
            key=key,
            label=label,
            aliases=aliases,
            openalex_ids=openalex_ids,
            normalized_aliases=normalized_aliases,
            normalized_openalex_ids=set(openalex_ids),
        )

    return OpenAlexAffiliationCatalog(
        path=_make_repo_relative_path(resolved),
        catalog_name=catalog_name,
        entities=entities,
    )


def load_openalex_affiliation_catalogs(paths: Iterable[str | Path]) -> list[OpenAlexAffiliationCatalog]:
    catalogs: list[OpenAlexAffiliationCatalog] = []
    for path in paths:
        try:
            catalogs.append(load_openalex_affiliation_catalog(path))
        except (FileNotFoundError, ValueError, OSError) as exc:
            _warn(f"[warn] OpenAlex affiliation catalog load failed for {path!r}: {exc}")
    return catalogs


def _warn(message: str) -> None:
    timestamped = f"{dt.datetime.now(dt.timezone.utc).isoformat()} {message}"
    try:
        DEFAULT_WARNING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEFAULT_WARNING_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(timestamped + "\n")
    except OSError:
        pass

    for stream_name in ("stderr", "__stderr__", "stdout", "__stdout__"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.write(timestamped + "\n")
            stream.flush()
            break
        except OSError:
            continue


def _load_simple_yaml(text: str) -> Any:
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, raw.strip()))

    if not lines:
        return {}

    value, idx = _parse_yaml_block(lines, 0, lines[0][0])
    if idx != len(lines):
        raise ValueError("Unsupported YAML structure near end of file")
    return value


def _parse_yaml_block(lines: list[tuple[int, str]], idx: int, indent: int) -> tuple[Any, int]:
    _, content = lines[idx]
    if content.startswith("- "):
        return _parse_yaml_list(lines, idx, indent)
    return _parse_yaml_dict(lines, idx, indent)


def _parse_yaml_dict(lines: list[tuple[int, str]], idx: int, indent: int) -> tuple[dict[str, Any], int]:
    data: dict[str, Any] = {}
    while idx < len(lines):
        line_indent, content = lines[idx]
        if line_indent < indent:
            break
        if line_indent != indent or content.startswith("- "):
            raise ValueError(f"Unsupported YAML mapping entry: {content}")

        key, sep, remainder = content.partition(":")
        if not sep:
            raise ValueError(f"Invalid YAML mapping entry: {content}")

        key = key.strip()
        remainder = remainder.strip()
        idx += 1

        if remainder:
            data[key] = _parse_yaml_scalar(remainder)
            continue

        if idx >= len(lines) or lines[idx][0] < indent:
            data[key] = None
            continue

        if lines[idx][0] == indent and not lines[idx][1].startswith("- "):
            data[key] = None
            continue

        data[key], idx = _parse_yaml_block(lines, idx, lines[idx][0])

    return data, idx


def _parse_yaml_list(lines: list[tuple[int, str]], idx: int, indent: int) -> tuple[list[Any], int]:
    data: list[Any] = []
    while idx < len(lines):
        line_indent, content = lines[idx]
        if line_indent < indent:
            break
        if line_indent != indent:
            raise ValueError(f"Unsupported YAML list indentation: {content}")
        if not content.startswith("- "):
            break

        remainder = content[2:].strip()
        idx += 1

        if remainder:
            data.append(_parse_yaml_scalar(remainder))
            continue

        if idx >= len(lines) or lines[idx][0] <= indent:
            data.append(None)
            continue

        item, idx = _parse_yaml_block(lines, idx, lines[idx][0])
        data.append(item)

    return data, idx


def _parse_yaml_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"null", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    if re.fullmatch(r"[+-]?\d+\.\d+", value):
        return float(value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        unquoted = value[1:-1]
        if value[0] == "'":
            return unquoted.replace("''", "'")
        return unquoted
    return value


def normalize_title(title: str) -> str:
    text = title.lower().strip()
    text = re.sub(r"[^0-9a-z]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def titles_compatible(expected: str | None, candidate: str | None) -> bool:
    left = normalize_title(expected or "")
    right = normalize_title(candidate or "")
    if not left or not right:
        return False
    if left == right:
        return True

    left_tokens = left.split()
    right_tokens = right.split()
    if len(left_tokens) < 3 or len(right_tokens) < 3:
        return False

    if left in right or right in left:
        shorter = min(len(left_tokens), len(right_tokens))
        if shorter >= 4:
            return True

    left_set = set(left_tokens)
    right_set = set(right_tokens)
    overlap = len(left_set & right_set)
    recall = overlap / max(1, min(len(left_set), len(right_set)))
    jaccard = overlap / max(1, len(left_set | right_set))
    ratio = SequenceMatcher(None, left, right).ratio()
    return recall >= 0.8 and (jaccard >= 0.5 or ratio >= 0.82)


def normalize_affiliation_name(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).casefold().strip()
    text = re.sub(r"[^0-9a-z]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_openalex_id(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().rstrip("/")
    if not text:
        return ""
    lowered = text.casefold()
    if lowered.startswith("https://openalex.org/"):
        return lowered
    if re.fullmatch(r"[a-z]\d+", lowered):
        return f"https://openalex.org/{lowered}"
    return lowered


def _make_repo_relative_path(path: str | Path, root: Path | None = None) -> str:
    resolved = Path(path).expanduser().resolve()
    repo_root = (root or Path(".")).resolve()
    try:
        return str(resolved.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return str(resolved)


def split_multiline_list(value: str) -> list[str]:
    return [part.strip() for part in value.splitlines() if part.strip()]


def parse_keywords_input(value: str | Iterable[str]) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[\n,]+", value)
    else:
        parts = list(value)

    out: list[str] = []
    seen: set[str] = set()
    for item in parts:
        normalized = str(item).strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def normalize_weight_map(weights: Mapping[str, float]) -> tuple[dict[str, float], float, bool]:
    positive_weights = {key: max(0.0, float(weights.get(key, 0.0))) for key in WEIGHT_KEYS}
    raw_sum = sum(positive_weights.values())
    if raw_sum <= 0:
        equal_weight = 1.0 / len(WEIGHT_KEYS)
        return ({key: equal_weight for key in WEIGHT_KEYS}, 0.0, True)
    normalized = {key: value / raw_sum for key, value in positive_weights.items()}
    return normalized, raw_sum, not math.isclose(raw_sum, 1.0, rel_tol=1e-9, abs_tol=1e-9)


def paper_from_dict(data: Mapping[str, Any]) -> Paper:
    allowed_fields = {item.name for item in fields(Paper)}
    payload = {key: value for key, value in dict(data).items() if key in allowed_fields}
    return Paper(**payload)


def clone_paper(paper: Paper) -> Paper:
    return paper_from_dict(asdict(paper))


def config_hash(config: Mapping[str, Any]) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_fetch_options_from_config(config: Mapping[str, Any]) -> FetchOptions:
    sources = config.get("sources", {})
    arxiv_cfg = sources.get("arxiv", {})
    openreview_cfg = sources.get("openreview", {})
    ss_cfg = sources.get("semanticscholar", {})
    openalex_cfg = sources.get("openalex", {})
    return FetchOptions(
        queries=[str(query).strip() for query in arxiv_cfg.get("queries", []) if str(query).strip()],
        categories=[str(cat).strip() for cat in arxiv_cfg.get("categories", []) if str(cat).strip()],
        days_back=int(arxiv_cfg.get("days_back_daily", 7)),
        max_results_per_query=int(arxiv_cfg.get("max_results_per_query", 100)),
        enable_semanticscholar=bool(ss_cfg.get("enabled", False)),
        semanticscholar_api_key_env=str(ss_cfg.get("api_key_env") or "SEMANTIC_SCHOLAR_API_KEY"),
        enable_openreview=bool(openreview_cfg.get("enabled", False)),
        openreview_venues=[
            str(venue).strip() for venue in openreview_cfg.get("venues", []) if str(venue).strip()
        ],
        openreview_keywords=parse_keywords_input(openreview_cfg.get("keywords", [])),
        enable_openalex=bool(openalex_cfg.get("enabled", False)),
        openalex_api_key_env=str(openalex_cfg.get("api_key_env") or "OPENALEX_API_KEY"),
    )


def build_rank_options_from_config(config: Mapping[str, Any]) -> RankOptions:
    ranking_cfg = config.get("ranking", {})
    priority_catalogs_cfg = ranking_cfg.get("openalex_priority_catalogs", [])
    if isinstance(priority_catalogs_cfg, str):
        priority_catalogs_cfg = [priority_catalogs_cfg]
    return RankOptions(
        include_keywords=parse_keywords_input(config.get("filters", {}).get("include_keywords", [])),
        exclude_keywords=parse_keywords_input(config.get("filters", {}).get("exclude_keywords", [])),
        weights={key: float(ranking_cfg.get("weights", {}).get(key, 0.0)) for key in WEIGHT_KEYS},
        buckets={key: float(ranking_cfg.get("buckets", {}).get(key, 0.0)) for key in BUCKET_KEYS},
        daily_top_k=int(config.get("digest", {}).get("daily_top_k", 8)),
        openalex_priority_catalogs=[
            str(path).strip()
            for path in priority_catalogs_cfg
            if str(path).strip()
        ],
    )


def build_digest_options_from_config(config: Mapping[str, Any]) -> DigestOptions:
    digest_cfg = config.get("digest", {})
    configured_tracks = [str(track).strip() for track in digest_cfg.get("tracks", []) if str(track).strip()]
    track_defs_cfg = digest_cfg.get("track_definitions") or {}
    track_definitions = copy.deepcopy(BUILTIN_TRACK_DEFINITIONS)
    for track_id, definition in track_defs_cfg.items():
        track_key = str(track_id)
        track_definitions[track_key] = _normalize_track_definition(track_key, definition)
    if TRACK_UNASSIGNED not in track_definitions:
        track_definitions[TRACK_UNASSIGNED] = {"label": "Unassigned", "keywords": []}
    return DigestOptions(
        daily_top_k=int(digest_cfg.get("daily_top_k", 8)),
        weekly_top_k_per_track=int(digest_cfg.get("weekly_top_k_per_track", 5)),
        tracks=configured_tracks or [TRACK_UNASSIGNED],
        track_definitions=track_definitions,
    )


def _normalize_track_definition(track_id: str, definition: Any) -> dict[str, Any]:
    if isinstance(definition, Mapping):
        return {
            "label": str(definition.get("label") or _default_track_label(track_id)),
            "keywords": parse_keywords_input(definition.get("keywords", [])),
        }
    return {
        "label": _default_track_label(track_id),
        "keywords": parse_keywords_input(definition),
    }


def _default_track_label(track_id: str) -> str:
    return str(track_id).replace("_", " ").strip().title() or str(track_id)


def build_config_from_options(
    base_config: Mapping[str, Any],
    fetch_options: FetchOptions,
    rank_options: RankOptions,
    digest_options: DigestOptions | None = None,
) -> dict[str, Any]:
    config = copy.deepcopy(dict(base_config))
    config.setdefault("sources", {})
    config["sources"].setdefault("arxiv", {})
    config["sources"].setdefault("semanticscholar", {})
    config["sources"].setdefault("openreview", {})
    config["sources"].setdefault("openalex", {})
    config.setdefault("filters", {})
    config.setdefault("ranking", {})
    config["ranking"].setdefault("weights", {})
    config["ranking"].setdefault("buckets", {})
    config.setdefault("digest", {})

    normalized_weights, _, _ = normalize_weight_map(rank_options.weights)

    config["sources"]["arxiv"]["queries"] = list(fetch_options.queries)
    config["sources"]["arxiv"]["categories"] = list(fetch_options.categories)
    config["sources"]["arxiv"]["days_back_daily"] = int(fetch_options.days_back)
    config["sources"]["arxiv"]["max_results_per_query"] = int(fetch_options.max_results_per_query)
    config["sources"]["semanticscholar"]["enabled"] = bool(fetch_options.enable_semanticscholar)
    config["sources"]["semanticscholar"]["api_key_env"] = fetch_options.semanticscholar_api_key_env
    config["sources"]["openreview"]["enabled"] = bool(fetch_options.enable_openreview)
    config["sources"]["openreview"]["venues"] = list(fetch_options.openreview_venues)
    config["sources"]["openreview"]["keywords"] = list(fetch_options.openreview_keywords)
    config["sources"]["openalex"]["enabled"] = bool(fetch_options.enable_openalex)
    config["sources"]["openalex"]["api_key_env"] = fetch_options.openalex_api_key_env
    config["filters"]["include_keywords"] = list(rank_options.include_keywords)
    config["filters"]["exclude_keywords"] = list(rank_options.exclude_keywords)
    config["ranking"]["weights"] = normalized_weights
    config["ranking"]["buckets"] = {key: float(rank_options.buckets.get(key, 0.0)) for key in BUCKET_KEYS}
    priority_catalogs = [str(path).strip() for path in rank_options.openalex_priority_catalogs if str(path).strip()]
    if priority_catalogs:
        config["ranking"]["openalex_priority_catalogs"] = priority_catalogs
    else:
        config["ranking"].pop("openalex_priority_catalogs", None)
    config["digest"]["daily_top_k"] = int(rank_options.daily_top_k)
    config.pop("llm", None)

    if digest_options is not None:
        config["digest"]["daily_top_k"] = int(digest_options.daily_top_k)
        config["digest"]["weekly_top_k_per_track"] = int(digest_options.weekly_top_k_per_track)
        config["digest"]["tracks"] = list(digest_options.tracks)
        custom_track_defs: dict[str, Any] = {}
        for track_id, definition in digest_options.track_definitions.items():
            builtin = BUILTIN_TRACK_DEFINITIONS.get(track_id)
            if builtin == definition:
                continue
            custom_track_defs[track_id] = {
                "label": definition.get("label", track_id),
                "keywords": list(definition.get("keywords", [])),
            }
        if custom_track_defs:
            config["digest"]["track_definitions"] = custom_track_defs
        else:
            config["digest"].pop("track_definitions", None)

    return config


def fetch_options_signature(fetch_options: FetchOptions) -> str:
    payload = {
        "queries": list(fetch_options.queries),
        "categories": list(fetch_options.categories),
        "days_back": int(fetch_options.days_back),
        "max_results_per_query": int(fetch_options.max_results_per_query),
        "enable_semanticscholar": bool(fetch_options.enable_semanticscholar),
        "enable_openreview": bool(fetch_options.enable_openreview),
        "openreview_venues": list(fetch_options.openreview_venues),
        "openreview_keywords": list(fetch_options.openreview_keywords),
        "enable_openalex": bool(fetch_options.enable_openalex),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def describe_keyword_hits(paper: Paper, rank_options: RankOptions) -> dict[str, list[str] | str | None]:
    text = _paper_text(paper)
    include_hits = [kw for kw in rank_options.include_keywords if kw in text]
    exclude_hits = [kw for kw in rank_options.exclude_keywords if kw in text]
    priority_matches = (paper.source_metadata.get("openalex") or {}).get("matched_priority_entities") or []
    return {
        "include_hits": include_hits,
        "exclude_hits": exclude_hits,
        "primary_track": paper.primary_track,
        "track_ids": list(paper.track_ids),
        "openalex_priority_matches": [dict(match) for match in priority_matches],
    }


def papers_to_records(papers: Iterable[Paper]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for paper in papers:
        records.append(
            {
                "title": paper.title,
                "final_score": paper.final_score,
                "bucket": paper.bucket,
                "primary_track": paper.primary_track,
                "published_at": paper.published_at,
                "categories": ", ".join(paper.categories),
                "citations": paper.citations,
                "source": paper.source,
                "venue": paper.venue,
                "decision": paper.decision,
                "review_signal": paper.review_signal,
                "priority_match": ", ".join(
                    sorted(
                        {
                            str(match.get("entity_label") or match.get("institution_display_name") or "").strip()
                            for match in ((paper.source_metadata.get("openalex") or {}).get("matched_priority_entities") or [])
                            if str(match.get("entity_label") or match.get("institution_display_name") or "").strip()
                        }
                    )
                ),
                "url": paper.url,
            }
        )
    return records


def compute_canonical_key(paper: Paper) -> str:
    doi = normalize_doi(paper.doi)
    if doi:
        return f"doi:{doi}"
    arxiv_id = extract_arxiv_id(paper)
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    if paper.source == "openreview" and paper.external_id:
        return f"openreview:{paper.external_id}"
    title_key = paper.normalized_title or normalize_title(paper.title)
    author_key = _author_signature(paper.authors)
    return f"title:{title_key}|authors:{author_key}"


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    text = doi.strip().lower()
    text = text.removeprefix("https://doi.org/")
    text = text.removeprefix("http://doi.org/")
    return text or None


def extract_arxiv_id(paper: Paper) -> str | None:
    if paper.source == "arxiv" and paper.external_id:
        return paper.external_id.lower()
    candidate = paper.source_metadata.get("arxiv", {}).get("external_id")
    if candidate:
        return str(candidate).lower()
    if paper.url:
        match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", paper.url)
        if match:
            return match.group(1).replace(".pdf", "").lower()
    return None


def merge_source_metadata(*payloads: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for payload in payloads:
        for key, value in payload.items():
            if key not in merged:
                merged[key] = copy.deepcopy(value)
            elif isinstance(merged[key], dict) and isinstance(value, Mapping):
                nested = dict(merged[key])
                nested.update(copy.deepcopy(dict(value)))
                merged[key] = nested
            elif isinstance(merged[key], list) and isinstance(value, Sequence) and not isinstance(value, str):
                merged[key] = list(dict.fromkeys([*merged[key], *list(value)]))
            elif value not in (None, "", [], {}):
                merged[key] = copy.deepcopy(value)
    return merged


def deduplicate(papers: Iterable[Paper]) -> list[Paper]:
    merged: list[Paper] = []
    by_key: dict[str, Paper] = {}
    by_title: dict[str, list[Paper]] = {}

    for paper in papers:
        candidate = clone_paper(paper)
        candidate.normalized_title = candidate.normalized_title or normalize_title(candidate.title)
        canonical_key = compute_canonical_key(candidate)
        if canonical_key in by_key:
            merged_paper = _merge_papers(by_key[canonical_key], candidate)
            by_key[canonical_key] = merged_paper
            _replace_in_list(merged, canonical_key, merged_paper)
            continue

        title_key = candidate.normalized_title or ""
        matched_existing = None
        for existing in by_title.get(title_key, []):
            if _author_overlap(existing.authors, candidate.authors) > 0 or not existing.authors or not candidate.authors:
                matched_existing = existing
                break
        if matched_existing is not None:
            existing_key = compute_canonical_key(matched_existing)
            merged_paper = _merge_papers(matched_existing, candidate)
            new_key = compute_canonical_key(merged_paper)
            by_key.pop(existing_key, None)
            by_key[new_key] = merged_paper
            _replace_in_list(merged, existing_key, merged_paper)
            by_title[title_key] = [merged_paper if item is matched_existing else item for item in by_title[title_key]]
            continue

        candidate.canonical_id = canonical_key
        by_key[canonical_key] = candidate
        by_title.setdefault(title_key, []).append(candidate)
        merged.append(candidate)

    for paper in merged:
        paper.canonical_id = compute_canonical_key(paper)
    return merged


def _replace_in_list(papers: list[Paper], canonical_key: str, replacement: Paper) -> None:
    for idx, item in enumerate(papers):
        if compute_canonical_key(item) == canonical_key:
            papers[idx] = replacement
            return


def _merge_papers(existing: Paper, candidate: Paper) -> Paper:
    merged = clone_paper(existing)
    merged.normalized_title = merged.normalized_title or normalize_title(merged.title)

    if SOURCE_PRIORITY.get(candidate.source, 0) > SOURCE_PRIORITY.get(merged.source, 0):
        merged.source = candidate.source
        merged.external_id = candidate.external_id or merged.external_id
        merged.url = candidate.url or merged.url
        merged.pdf_url = candidate.pdf_url or merged.pdf_url

    if len(candidate.abstract or "") > len(merged.abstract or ""):
        merged.abstract = candidate.abstract
    if candidate.title and len(candidate.title) > len(merged.title):
        merged.title = candidate.title
    if candidate.venue and not merged.venue:
        merged.venue = candidate.venue
    if candidate.venue and candidate.source == "openreview":
        merged.venue = candidate.venue
    merged.authors = list(dict.fromkeys([*merged.authors, *candidate.authors]))
    merged.categories = list(dict.fromkeys([*merged.categories, *candidate.categories]))
    merged.topics = list(dict.fromkeys([*merged.topics, *candidate.topics]))
    merged.doi = normalize_doi(merged.doi) or normalize_doi(candidate.doi)
    merged.published_at = _choose_iso_time(merged.published_at, candidate.published_at, prefer_earliest=True)
    merged.updated_at = _choose_iso_time(merged.updated_at, candidate.updated_at, prefer_earliest=False)
    merged.citations = max(x for x in [merged.citations, candidate.citations] if x is not None) if any(
        x is not None for x in [merged.citations, candidate.citations]
    ) else None
    merged.decision = candidate.decision or merged.decision
    merged.review_count = max(merged.review_count, candidate.review_count)
    merged.review_signal = _max_optional(merged.review_signal, candidate.review_signal)
    merged.source_metadata = merge_source_metadata(merged.source_metadata, candidate.source_metadata)
    merged.raw = merge_source_metadata(merged.raw, candidate.raw)
    merged.canonical_id = compute_canonical_key(merged)
    return merged


def _author_signature(authors: Sequence[str]) -> str:
    if not authors:
        return "none"
    normalized = [normalize_title(author).replace(" ", "") for author in authors[:4]]
    return "|".join(sorted(filter(None, normalized)))


def _author_overlap(left: Sequence[str], right: Sequence[str]) -> int:
    left_set = {normalize_title(author).replace(" ", "") for author in left if author}
    right_set = {normalize_title(author).replace(" ", "") for author in right if author}
    return len(left_set & right_set)


def _max_optional(left: float | None, right: float | None) -> float | None:
    values = [value for value in (left, right) if value is not None]
    return max(values) if values else None


def _max_int(left: int | None, right: int | None) -> int | None:
    values = [int(value) for value in (left, right) if value is not None]
    return max(values) if values else None


def _choose_iso_time(left: str | None, right: str | None, prefer_earliest: bool) -> str | None:
    left_dt = _parse_any_datetime(left)
    right_dt = _parse_any_datetime(right)
    candidates = [value for value in (left_dt, right_dt) if value is not None]
    if not candidates:
        return left or right
    chosen = min(candidates) if prefer_earliest else max(candidates)
    return chosen.isoformat().replace("+00:00", "Z")


class ArxivClient:
    """Minimal arXiv collector using the public Atom feed API."""

    def __init__(self, pause_s: float = 3.0, page_size: int = 100) -> None:
        self.pause_s = pause_s
        self.page_size = max(1, min(page_size, 100))

    def search(
        self,
        query: str,
        categories: list[str],
        days_back: int,
        max_results: int = 100,
        sort_by: str = "submittedDate",
        sort_order: str = "descending",
    ) -> list[Paper]:
        cat_clause = " OR ".join(f"cat:{c}" for c in categories) if categories else ""
        full_query = query
        if cat_clause:
            full_query = f"({query}) AND ({cat_clause})"
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(0, int(days_back)))

        collected: list[Paper] = []
        start = 0

        while len(collected) < max(0, int(max_results)):
            page_limit = min(self.page_size, max_results - len(collected))
            batch = self._search_page(
                full_query=full_query,
                start=start,
                max_results=page_limit,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            if not batch:
                break

            recent_papers = [paper for paper in batch if self._is_recent_enough(paper.published_at, cutoff)]
            collected.extend(recent_papers)

            if len(collected) >= max_results:
                break
            if len(batch) < page_limit:
                break
            if not recent_papers:
                break

            start += len(batch)

        return collected[:max_results]

    def _search_page(
        self,
        full_query: str,
        start: int,
        max_results: int,
        sort_by: str,
        sort_order: str,
    ) -> list[Paper]:
        params = {
            "search_query": full_query,
            "start": start,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
        headers = {"User-Agent": "paper-radar-harness/0.2 (+research scout)"}
        try:
            resp = requests.get(ARXIV_API, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
        except (requests.RequestException, OSError) as exc:
            _warn(f"[warn] arXiv query failed for {full_query!r}: {exc}")
            return []
        time.sleep(self.pause_s)
        return self._parse(resp.text)

    def _parse(self, xml_text: str) -> list[Paper]:
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            _warn(f"[warn] Failed to parse arXiv response: {exc}")
            return []
        papers: list[Paper] = []
        for entry in root.findall("atom:entry", ns):
            entry_id = entry.findtext("atom:id", default="", namespaces=ns)
            title = _clean(entry.findtext("atom:title", default="", namespaces=ns))
            abstract = _clean(entry.findtext("atom:summary", default="", namespaces=ns))
            published = entry.findtext("atom:published", default=None, namespaces=ns)
            updated = entry.findtext("atom:updated", default=None, namespaces=ns)
            authors = [
                _clean(a.findtext("atom:name", default="", namespaces=ns))
                for a in entry.findall("atom:author", ns)
            ]
            cats = [c.attrib.get("term", "") for c in entry.findall("atom:category", ns)]
            pdf_url = None
            doi = None
            for link in entry.findall("atom:link", ns):
                if link.attrib.get("title") == "pdf":
                    pdf_url = link.attrib.get("href")
            doi_node = entry.find("arxiv:doi", ns)
            if doi_node is not None and doi_node.text:
                doi = doi_node.text.strip()

            external_id = entry_id.rsplit("/", 1)[-1]
            papers.append(
                Paper(
                    source="arxiv",
                    external_id=external_id,
                    title=title,
                    abstract=abstract,
                    authors=authors,
                    published_at=published,
                    updated_at=updated,
                    url=entry_id,
                    pdf_url=pdf_url,
                    categories=cats,
                    doi=doi,
                    raw={"arxiv": {"entry_id": entry_id}},
                    source_metadata={
                        "arxiv": {
                            "external_id": external_id,
                            "entry_id": entry_id,
                            "categories": cats,
                        }
                    },
                    normalized_title=normalize_title(title),
                )
            )
        return papers

    @staticmethod
    def _is_recent_enough(published_at: str | None, cutoff: dt.datetime) -> bool:
        published = _parse_any_datetime(published_at)
        if not published:
            return False
        return published >= cutoff


class OpenReviewClient:
    def __init__(self, pause_s: float = 0.5, page_size: int = 200) -> None:
        self.pause_s = pause_s
        self.page_size = page_size

    def collect(
        self,
        venues: Sequence[str],
        keywords: Sequence[str],
        days_back: int,
    ) -> tuple[list[Paper], dict[str, Any]]:
        collected: list[Paper] = []
        status = {"enabled": True, "venues": {}, "errors": []}
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(0, int(days_back)))
        lowered_keywords = [keyword.lower() for keyword in keywords if keyword]

        for venue in venues:
            venue_notes = self._fetch_venue_notes(venue)
            matched = 0
            papers: list[Paper] = []
            for note in venue_notes:
                paper = self._paper_from_note(note, venue)
                if not paper:
                    continue
                published = _parse_any_datetime(paper.published_at or paper.updated_at)
                if published is not None and published < cutoff:
                    continue
                if lowered_keywords:
                    text = _paper_text(paper)
                    if not any(keyword in text for keyword in lowered_keywords):
                        continue
                papers.append(paper)
                matched += 1
            collected.extend(papers)
            status["venues"][venue] = {"fetched": len(venue_notes), "matched": matched}

        return collected, status

    def _fetch_venue_notes(self, venue: str) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        errors: list[str] = []
        for invitation_suffix in ("Blind_Submission", "Submission"):
            invitation = f"{venue}/-/{invitation_suffix}"
            offset = 0
            while True:
                params = {
                    "invitation": invitation,
                    "details": "directReplies",
                    "limit": self.page_size,
                    "offset": offset,
                }
                try:
                    response = requests.get(OPENREVIEW_API, params=params, timeout=30)
                    response.raise_for_status()
                    payload = response.json()
                except (requests.RequestException, ValueError, OSError) as exc:
                    errors.append(f"{invitation}: {exc}")
                    break
                batch = payload.get("notes") or payload.get("results") or []
                if batch:
                    notes.extend(batch)
                if len(batch) < self.page_size:
                    break
                offset += len(batch)
                time.sleep(self.pause_s)
            if notes:
                return notes
        for error in errors:
            _warn(f"[warn] OpenReview query failed: {error}")
        return notes

    def _paper_from_note(self, note: Mapping[str, Any], venue: str) -> Paper | None:
        content = note.get("content") or {}
        title = _content_value(content, "title")
        abstract = _content_value(content, "abstract")
        if not title or not abstract:
            return None
        authors = _normalize_author_list(_content_value(content, "authors"))
        keywords = _normalize_string_list(_content_value(content, "keywords"))
        forum_id = str(note.get("forum") or note.get("id") or "")
        note_id = str(note.get("id") or forum_id)
        replies = list((note.get("details") or {}).get("directReplies") or [])
        decision, review_signal, review_count = self._extract_review_signal(replies)
        doi = normalize_doi(_content_value(content, "doi"))
        published_at = _ms_to_iso(note.get("pdate") or note.get("odate") or note.get("cdate"))
        updated_at = _ms_to_iso(note.get("mdate") or note.get("tcdate"))
        raw_payload = {"note_id": note_id, "forum_id": forum_id, "reply_count": len(replies)}
        return Paper(
            source="openreview",
            external_id=forum_id or note_id,
            title=_clean(str(title)),
            abstract=_clean(str(abstract)),
            authors=authors,
            published_at=published_at,
            updated_at=updated_at,
            url=f"https://openreview.net/forum?id={forum_id or note_id}",
            pdf_url=f"https://openreview.net/pdf?id={forum_id or note_id}",
            venue=venue,
            categories=[],
            doi=doi,
            topics=keywords,
            decision=decision,
            review_signal=review_signal,
            review_count=review_count,
            normalized_title=normalize_title(str(title)),
            source_metadata={
                "openreview": {
                    "forum_id": forum_id or note_id,
                    "note_id": note_id,
                    "keywords": keywords,
                    "decision": decision,
                    "review_count": review_count,
                    "review_signal": review_signal,
                    "venue": venue,
                }
            },
            raw={"openreview": raw_payload},
        )

    def _extract_review_signal(self, replies: Sequence[Mapping[str, Any]]) -> tuple[str | None, float | None, int]:
        decision = None
        ratings: list[float] = []
        confidences: list[float] = []
        review_count = 0
        for reply in replies:
            invitation = str(reply.get("invitation", ""))
            content = reply.get("content") or {}
            if invitation.endswith("Decision"):
                decision = _content_value(content, "decision") or decision
            if invitation.endswith("Official_Review"):
                review_count += 1
                rating = _extract_numeric_value(_content_value(content, "rating"))
                confidence = _extract_numeric_value(_content_value(content, "confidence"))
                if rating is not None:
                    ratings.append(rating)
                if confidence is not None:
                    confidences.append(confidence)
        review_signal = None
        if ratings or confidences:
            review_signal = (sum(ratings) / len(ratings) if ratings else 0.0) * 8.0
            if confidences:
                review_signal += (sum(confidences) / len(confidences)) * 4.0
            review_signal = min(review_signal, 100.0)
        return decision, review_signal, review_count


class SemanticScholarClient:
    """Optional metadata enricher. Expects an API key for heavy usage."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def enrich_title(self, paper: Paper) -> Paper:
        headers = {"User-Agent": "paper-radar-harness/0.2 (+research scout)"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        params = {
            "query": paper.title,
            "fields": "title,year,venue,citationCount,openAccessPdf,externalIds,fieldsOfStudy,url",
            "sort": "citationCount:desc",
        }
        try:
            resp = requests.get(SEMANTIC_SCHOLAR_API, params=params, headers=headers, timeout=30)
        except (requests.RequestException, OSError) as exc:
            _warn(f"[warn] Semantic Scholar lookup failed for {paper.title!r}: {exc}")
            return paper
        if resp.status_code != 200:
            _warn(f"[warn] Semantic Scholar returned {resp.status_code} for {paper.title!r}")
            return paper
        try:
            data = resp.json().get("data", [])
        except ValueError as exc:
            _warn(f"[warn] Invalid Semantic Scholar response for {paper.title!r}: {exc}")
            return paper
        if not data:
            return paper
        best = next(
            (
                candidate
                for candidate in data
                if titles_compatible(paper.title, candidate.get("title"))
            ),
            None,
        )
        if best is None:
            return paper
        paper.citations = _max_int(paper.citations, best.get("citationCount"))
        paper.venue = paper.venue or best.get("venue")
        fos = best.get("fieldsOfStudy") or []
        paper.topics = list(dict.fromkeys([*paper.topics, *[str(x) for x in fos]]))
        ext = best.get("externalIds") or {}
        if not paper.doi and ext.get("DOI"):
            paper.doi = normalize_doi(ext["DOI"])
        oa_pdf = best.get("openAccessPdf") or {}
        if not paper.pdf_url and oa_pdf.get("url"):
            paper.pdf_url = oa_pdf["url"]
        paper.source_metadata = merge_source_metadata(
            paper.source_metadata,
            {
                "semanticscholar": {
                    "citation_count": best.get("citationCount"),
                    "venue": best.get("venue"),
                    "fields_of_study": fos,
                    "url": best.get("url"),
                }
            },
        )
        return paper


class OpenAlexClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def enrich(self, paper: Paper) -> Paper:
        candidate = self._lookup_work(paper)
        if not candidate:
            return paper

        paper.citations = _max_int(paper.citations, candidate.get("cited_by_count"))
        paper.doi = paper.doi or normalize_doi(candidate.get("doi"))
        primary_location = candidate.get("primary_location") or {}
        source = primary_location.get("source") or {}
        paper.venue = paper.venue or source.get("display_name")
        primary_topic = candidate.get("primary_topic") or {}
        topics = [primary_topic.get("display_name")] if primary_topic.get("display_name") else []
        concepts = [
            concept.get("display_name")
            for concept in (candidate.get("concepts") or [])
            if concept.get("display_name")
        ]
        institutions = extract_openalex_institutions(candidate)
        paper.topics = list(dict.fromkeys([*paper.topics, *topics, *concepts]))
        if not paper.pdf_url:
            open_access = candidate.get("open_access") or {}
            paper.pdf_url = open_access.get("oa_url") or paper.pdf_url
        paper.source_metadata = merge_source_metadata(
            paper.source_metadata,
            {
                "openalex": {
                    "id": candidate.get("id"),
                    "cited_by_count": candidate.get("cited_by_count"),
                    "primary_topic": primary_topic.get("display_name"),
                    "concepts": concepts,
                    "primary_location": source.get("display_name"),
                    "oa_status": (candidate.get("open_access") or {}).get("oa_status"),
                    "is_oa": (candidate.get("open_access") or {}).get("is_oa"),
                    "institutions": institutions,
                }
            },
        )
        return paper

    def _lookup_work(self, paper: Paper) -> dict[str, Any] | None:
        for params in self._candidate_queries(paper):
            payload = self._query(params)
            results = payload.get("results") or []
            for candidate in results:
                if titles_compatible(paper.title, candidate.get("title")):
                    return candidate
        return None

    def _candidate_queries(self, paper: Paper) -> list[dict[str, Any]]:
        queries: list[dict[str, Any]] = []
        doi = normalize_doi(paper.doi)
        if doi:
            queries.append({"filter": f"doi:{doi}"})
        arxiv_id = extract_arxiv_id(paper)
        if arxiv_id:
            queries.append({"search": arxiv_id})
        queries.append({"filter": f"title.search:{paper.title}"})
        queries.append({"search": paper.title})
        return queries

    def _query(self, params: Mapping[str, Any]) -> dict[str, Any]:
        query_params = dict(params)
        query_params.setdefault("per-page", 5)
        query_params.setdefault("sort", "cited_by_count:desc")
        try:
            response = _openalex_get(OPENALEX_WORKS_API, params=query_params, api_key=self.api_key, timeout=30)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError, OSError) as exc:
            _warn(f"[warn] OpenAlex lookup failed for {params!r}: {exc}")
            return {}
        return data


def extract_openalex_institutions(candidate: Mapping[str, Any]) -> list[dict[str, str | None]]:
    institutions: list[dict[str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for authorship in candidate.get("authorships") or []:
        for institution in authorship.get("institutions") or []:
            institution_id = normalize_openalex_id(institution.get("id"))
            display_name = str(institution.get("display_name") or "").strip()
            ror = str(institution.get("ror") or "").strip() or None
            dedupe_key = (institution_id, normalize_affiliation_name(display_name))
            if dedupe_key in seen or not (institution_id or display_name):
                continue
            seen.add(dedupe_key)
            institutions.append(
                {
                    "id": institution_id or None,
                    "display_name": display_name or None,
                    "ror": ror,
                }
            )
    return institutions


def openalex_self_check(
    api_key_env: str = "OPENALEX_API_KEY",
    env: Mapping[str, str] | None = None,
    timeout_s: float = 15.0,
    search_paths: Sequence[Path] | None = None,
) -> dict[str, Any]:
    api_key, env_source = _resolve_api_key(api_key_env, env=env, search_paths=search_paths)
    result: dict[str, Any] = {
        "api_key_env": api_key_env,
        "env_present": bool(api_key),
        "env_source": env_source,
        "api_key_masked": _mask_api_key(api_key),
        "api_key_length": len(api_key or ""),
        "http_ok": False,
        "status_code": None,
        "daily_remaining_usd": None,
        "resets_at": None,
        "message": "",
    }
    if not api_key:
        result["message"] = f"{api_key_env} is not set."
        return result

    try:
        response = _openalex_get(OPENALEX_RATE_LIMIT_API, api_key=api_key, timeout=timeout_s)
        result["status_code"] = response.status_code
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, OSError) as exc:
        result["message"] = f"OpenAlex self-check failed: {exc}"
        return result

    rate_limit = payload.get("rate_limit") or {}
    result.update(
        {
            "http_ok": True,
            "daily_remaining_usd": rate_limit.get("daily_remaining_usd"),
            "resets_at": rate_limit.get("resets_at"),
            "message": "OpenAlex API key verified.",
        }
    )
    return result


def _openalex_get(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    api_key: str | None = None,
    timeout: float = 30,
) -> requests.Response:
    query_params = dict(params or {})
    if api_key:
        query_params["api_key"] = api_key
    headers = {"User-Agent": "paper-radar-harness/0.2 (+research scout)"}
    return requests.get(url, params=query_params, headers=headers, timeout=timeout)


def _resolve_api_key(
    env_name: str,
    *,
    env: Mapping[str, str] | None = None,
    search_paths: Sequence[Path] | None = None,
) -> tuple[str | None, str | None]:
    env_map = os.environ if env is None else env
    direct_value = env_map.get(env_name)
    if direct_value:
        return direct_value, "process"

    candidate_paths = tuple(search_paths) if search_paths is not None else None
    if candidate_paths is None and env is not None:
        return None, None
    if candidate_paths is None:
        home = Path.home()
        candidate_paths = (
            home / ".profile",
            home / ".bash_profile",
            home / ".bashrc",
        )

    for path in candidate_paths:
        file_value = _read_exported_env_value(path, env_name)
        if file_value:
            return file_value, str(path)
    return None, None


def _read_exported_env_value(path: Path, env_name: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    pattern = re.compile(rf"^\s*export\s+{re.escape(env_name)}=(.+?)\s*$")
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        try:
            tokens = shlex.split(match.group(1), comments=True, posix=True)
        except ValueError:
            continue
        if tokens:
            return tokens[0]
    return None


def _mask_api_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}...{value[-3:]}"


def match_openalex_priority_entities(
    paper: Paper,
    catalogs: Sequence[OpenAlexAffiliationCatalog],
) -> list[dict[str, str | None]]:
    openalex_meta = paper.source_metadata.get("openalex") or {}
    institutions = openalex_meta.get("institutions") or []
    if not catalogs or not institutions:
        return []

    matches: list[dict[str, str | None]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for institution in institutions:
        institution_id = normalize_openalex_id(institution.get("id"))
        institution_name = str(institution.get("display_name") or "").strip()
        normalized_name = normalize_affiliation_name(institution_name)
        for catalog in catalogs:
            for entity in catalog.entities.values():
                match_type: str | None = None
                if institution_id and institution_id in entity.normalized_openalex_ids:
                    match_type = "openalex_id"
                elif normalized_name and normalized_name in entity.normalized_aliases:
                    match_type = "alias"
                if not match_type:
                    continue
                dedupe_key = (catalog.path, entity.key, institution_id, normalized_name)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                matches.append(
                    {
                        "catalog_name": catalog.catalog_name,
                        "catalog_path": catalog.path,
                        "entity_key": entity.key,
                        "entity_label": entity.label,
                        "institution_id": institution_id or None,
                        "institution_display_name": institution_name or None,
                        "match_type": match_type,
                    }
                )
    return matches


def set_openalex_priority_matches(paper: Paper, matches: Sequence[Mapping[str, Any]]) -> None:
    openalex_meta = copy.deepcopy(dict(paper.source_metadata.get("openalex") or {}))
    if not openalex_meta and not matches:
        return
    openalex_meta["matched_priority_entities"] = [dict(item) for item in matches]
    paper.source_metadata = merge_source_metadata(paper.source_metadata, {"openalex": openalex_meta})


class RuleRanker:
    def __init__(self, rank_options: RankOptions) -> None:
        self.include_keywords = [kw.lower() for kw in rank_options.include_keywords]
        self.exclude_keywords = [kw.lower() for kw in rank_options.exclude_keywords]
        self.weights, _, _ = normalize_weight_map(rank_options.weights)
        self.buckets = rank_options.buckets
        self.openalex_priority_catalogs = load_openalex_affiliation_catalogs(rank_options.openalex_priority_catalogs)

    def score(self, paper: Paper) -> Paper:
        text = _paper_text(paper)
        relevance_hits = sum(1 for kw in self.include_keywords if kw in text)
        exclude_hits = sum(1 for kw in self.exclude_keywords if kw in text)

        paper.relevance_score = min(100.0, relevance_hits * 12.5)
        if "cs.ro" in [c.lower() for c in paper.categories]:
            paper.relevance_score = min(100.0, paper.relevance_score + 20.0)
        if paper.primary_track and paper.primary_track != TRACK_UNASSIGNED:
            paper.relevance_score = min(100.0, paper.relevance_score + 10.0)

        novelty_terms = [
            "we propose",
            "introduce",
            "novel",
            "new benchmark",
            "new dataset",
            "first",
            "generalist",
            "foundation model",
            "vision-language-action",
            "world model",
        ]
        paper.novelty_score = min(100.0, sum(10 for term in novelty_terms if term in text))

        empirical_terms = [
            "real robot",
            "real-world",
            "ablation",
            "baseline",
            "simulation",
            "hardware",
            "policy",
            "dataset",
            "benchmark",
        ]
        paper.empirical_score = min(100.0, sum(8 for term in empirical_terms if term in text))

        paper.source_signal_score = self._source_signal_score(paper, text)
        paper.momentum_score = (
            0.0 if paper.citations is None else min(100.0, math.log1p(paper.citations) * 20.0)
        )
        paper.recency_score = self._recency_score(paper.published_at or paper.updated_at)
        paper.actionability_score = min(
            100.0,
            sum(
                12.5
                for term in (
                    "manipulation",
                    "policy",
                    "robot",
                    "embodied",
                    "visuomotor",
                    "humanoid",
                    "vla",
                    "world model",
                    "alignment",
                    "reward model",
                )
                if term in text
            ),
        )

        if exclude_hits > 0:
            paper.final_score = 0.0
            paper.bucket = "archive"
            return paper

        score = (
            self.weights["relevance"] * paper.relevance_score
            + self.weights["novelty"] * paper.novelty_score
            + self.weights["empirical"] * paper.empirical_score
            + self.weights["source_signal"] * paper.source_signal_score
            + self.weights["momentum"] * paper.momentum_score
            + self.weights["recency"] * paper.recency_score
            + self.weights["actionability"] * paper.actionability_score
        )
        paper.final_score = round(score, 2)
        paper.bucket = self._bucket(paper.final_score)
        return paper

    def _source_signal_score(self, paper: Paper, text: str) -> float:
        score = 0.0
        if paper.source == "arxiv" or "arxiv" in paper.source_metadata:
            score += 20.0
        if paper.source == "openreview" or "openreview" in paper.source_metadata:
            score += 20.0
        if paper.decision and "accept" in paper.decision.lower():
            score += 20.0
        if paper.review_signal is not None:
            score += min(30.0, paper.review_signal * 0.3)
        openalex_meta = paper.source_metadata.get("openalex") or {}
        if openalex_meta.get("is_oa"):
            score += 5.0
        if paper.venue:
            score += 5.0
        if "benchmark" in text or "dataset" in text:
            score += 5.0
        priority_matches = match_openalex_priority_entities(paper, self.openalex_priority_catalogs)
        set_openalex_priority_matches(paper, priority_matches)
        if priority_matches:
            score += OPENALEX_PRIORITY_BONUS
        return min(100.0, score)

    def _bucket(self, score: float) -> str:
        if score >= self.buckets.get("must_read", 85):
            return "must_read"
        if score >= self.buckets.get("worth_reading", 70):
            return "worth_reading"
        if score >= self.buckets.get("skim", 55):
            return "skim"
        return "archive"

    def _recency_score(self, published_at: str | None) -> float:
        pub = _parse_any_datetime(published_at)
        if not pub:
            return 20.0
        delta_days = max(0.0, (dt.datetime.now(dt.timezone.utc) - pub).days)
        return max(0.0, 100.0 - delta_days * 3.0)

class PaperRadarStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_hash TEXT NOT NULL,
                    config_path TEXT,
                    config_json TEXT NOT NULL,
                    fetch_signature TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    total_papers INTEGER DEFAULT 0,
                    source_status_json TEXT,
                    daily_digest TEXT,
                    weekly_digest TEXT
                );

                CREATE TABLE IF NOT EXISTS papers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_key TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    paper_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id INTEGER NOT NULL,
                    source_name TEXT NOT NULL,
                    source_id TEXT,
                    source_json TEXT NOT NULL,
                    UNIQUE(paper_id, source_name, source_id),
                    FOREIGN KEY(paper_id) REFERENCES papers(id)
                );

                CREATE TABLE IF NOT EXISTS run_rankings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    paper_id INTEGER NOT NULL,
                    rank_index INTEGER NOT NULL,
                    final_score REAL NOT NULL,
                    bucket TEXT,
                    score_json TEXT NOT NULL,
                    paper_snapshot TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id),
                    FOREIGN KEY(paper_id) REFERENCES papers(id)
                );

                CREATE TABLE IF NOT EXISTS track_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    paper_id INTEGER NOT NULL,
                    track_id TEXT NOT NULL,
                    is_primary INTEGER NOT NULL,
                    reason_json TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id),
                    FOREIGN KEY(paper_id) REFERENCES papers(id)
                );
                """
            )

    def start_run(
        self,
        *,
        config_hash_value: str,
        config_path: str | None,
        config: Mapping[str, Any],
        fetch_signature: str,
    ) -> int:
        started_at = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO runs (
                    config_hash, config_path, config_json, fetch_signature, started_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    config_hash_value,
                    config_path,
                    json.dumps(config, ensure_ascii=False, sort_keys=True),
                    fetch_signature,
                    started_at,
                    "running",
                ),
            )
            return int(cursor.lastrowid)

    def finalize_run(
        self,
        run_id: int,
        *,
        status: str,
        total_papers: int,
        source_status: Mapping[str, Any],
        daily_digest: str = "",
        weekly_digest: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET finished_at = ?, status = ?, total_papers = ?, source_status_json = ?, daily_digest = ?, weekly_digest = ?
                WHERE id = ?
                """,
                (
                    dt.datetime.now(dt.timezone.utc).isoformat(),
                    status,
                    total_papers,
                    json.dumps(source_status, ensure_ascii=False, sort_keys=True),
                    daily_digest,
                    weekly_digest,
                    run_id,
                ),
            )

    def persist_ranked_run(self, run_id: int, papers: Sequence[Paper]) -> None:
        with self._connect() as connection:
            for index, paper in enumerate(papers, start=1):
                paper_id = self._upsert_paper(connection, paper)
                self._upsert_paper_sources(connection, paper_id, paper)
                connection.execute(
                    """
                    INSERT INTO run_rankings (
                        run_id, paper_id, rank_index, final_score, bucket, score_json, paper_snapshot
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        paper_id,
                        index,
                        paper.final_score,
                        paper.bucket,
                        json.dumps(_score_payload(paper), ensure_ascii=False, sort_keys=True),
                        json.dumps(asdict(paper), ensure_ascii=False, sort_keys=True),
                    ),
                )
                self._insert_tracks(connection, run_id, paper_id, paper)

    def load_run_papers(self, run_id: int) -> list[Paper]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT paper_snapshot
                FROM run_rankings
                WHERE run_id = ?
                ORDER BY rank_index ASC
                """,
                (run_id,),
            ).fetchall()
        papers: list[Paper] = []
        for row in rows:
            payload = json.loads(row["paper_snapshot"])
            papers.append(paper_from_dict(payload))
        return papers

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row is not None else None

    def list_runs_for_config_hash(self, config_hash_value: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, config_hash, config_path, fetch_signature, started_at, finished_at, status, total_papers
                FROM runs
                WHERE config_hash = ?
                ORDER BY id DESC
                """,
                (config_hash_value,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_latest_run_by_config_hash(self, config_hash_value: str) -> dict[str, Any] | None:
        runs = self.list_runs_for_config_hash(config_hash_value)
        return runs[0] if runs else None

    def list_recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, config_hash, config_path, fetch_signature, started_at, finished_at, status, total_papers
                FROM runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _upsert_paper(self, connection: sqlite3.Connection, paper: Paper) -> int:
        canonical_key = compute_canonical_key(paper)
        payload = json.dumps(asdict(paper), ensure_ascii=False, sort_keys=True)
        row = connection.execute(
            "SELECT id FROM papers WHERE canonical_key = ?",
            (canonical_key,),
        ).fetchone()
        timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
        if row is None:
            cursor = connection.execute(
                """
                INSERT INTO papers (
                    canonical_key, source, external_id, title, paper_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (canonical_key, paper.source, paper.external_id, paper.title, payload, timestamp),
            )
            return int(cursor.lastrowid)
        paper_id = int(row["id"])
        connection.execute(
            """
            UPDATE papers
            SET source = ?, external_id = ?, title = ?, paper_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (paper.source, paper.external_id, paper.title, payload, timestamp, paper_id),
        )
        return paper_id

    def _upsert_paper_sources(self, connection: sqlite3.Connection, paper_id: int, paper: Paper) -> None:
        source_payloads = dict(paper.source_metadata)
        if paper.source not in source_payloads:
            source_payloads[paper.source] = {"external_id": paper.external_id}
        for source_name, payload in source_payloads.items():
            source_id = None
            if isinstance(payload, Mapping):
                source_id = payload.get("id") or payload.get("external_id") or payload.get("forum_id")
            connection.execute(
                """
                INSERT OR REPLACE INTO paper_sources (paper_id, source_name, source_id, source_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    paper_id,
                    source_name,
                    str(source_id) if source_id is not None else None,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )

    def _insert_tracks(self, connection: sqlite3.Connection, run_id: int, paper_id: int, paper: Paper) -> None:
        if not paper.track_ids:
            return
        for track_id in paper.track_ids:
            reason = paper.track_reasons.get(track_id, [])
            connection.execute(
                """
                INSERT INTO track_assignments (run_id, paper_id, track_id, is_primary, reason_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    paper_id,
                    track_id,
                    1 if track_id == paper.primary_track else 0,
                    json.dumps(reason, ensure_ascii=False),
                ),
            )


def collect_openreview(fetch_options: FetchOptions, pause_s: float = 0.5) -> tuple[list[Paper], dict[str, Any]]:
    if not fetch_options.enable_openreview:
        return [], {"enabled": False}
    client = OpenReviewClient(pause_s=pause_s)
    return client.collect(
        venues=fetch_options.openreview_venues,
        keywords=fetch_options.openreview_keywords,
        days_back=fetch_options.days_back,
    )


def collect_papers(fetch_options: FetchOptions, pause_s: float = 3.0) -> tuple[list[Paper], dict[str, Any]]:
    papers: list[Paper] = []
    source_status: dict[str, Any] = {"arxiv": {"enabled": True, "queries": {}}, "openreview": {"enabled": False}}

    collector = ArxivClient(pause_s=pause_s)
    for query in fetch_options.queries:
        batch = collector.search(
            query=query,
            categories=fetch_options.categories,
            days_back=fetch_options.days_back,
            max_results=fetch_options.max_results_per_query,
        )
        papers.extend(batch)
        source_status["arxiv"]["queries"][query] = {"count": len(batch)}

    openreview_papers, openreview_status = collect_openreview(fetch_options, pause_s=min(pause_s, 0.5))
    papers.extend(openreview_papers)
    source_status["openreview"] = openreview_status
    return deduplicate(papers), source_status


def fetch_papers(fetch_options: FetchOptions, pause_s: float = 3.0) -> list[Paper]:
    papers, _ = collect_papers(fetch_options, pause_s=pause_s)
    return papers


def enrich_openalex(
    papers: Iterable[Paper],
    fetch_options: FetchOptions,
    env: Mapping[str, str] | None = None,
    sleep_s: float = 0.2,
) -> tuple[list[Paper], dict[str, Any]]:
    cloned = [clone_paper(paper) for paper in papers]
    if not fetch_options.enable_openalex:
        return cloned, {"enabled": False}

    api_key, env_source = _resolve_api_key(fetch_options.openalex_api_key_env, env=env)
    client = OpenAlexClient(api_key=api_key)
    enriched: list[Paper] = []
    success_count = 0
    for paper in cloned:
        before = json.dumps(paper.source_metadata.get("openalex"), sort_keys=True, ensure_ascii=False)
        paper = client.enrich(paper)
        after = json.dumps(paper.source_metadata.get("openalex"), sort_keys=True, ensure_ascii=False)
        if after != before and paper.source_metadata.get("openalex"):
            success_count += 1
        enriched.append(paper)
        time.sleep(sleep_s)
    return enriched, {"enabled": True, "enriched": success_count, "env_source": env_source}


def enrich_papers_with_status(
    papers: Iterable[Paper],
    fetch_options: FetchOptions,
    env: Mapping[str, str] | None = None,
    sleep_s: float = 0.5,
) -> tuple[list[Paper], dict[str, Any]]:
    cloned = [clone_paper(paper) for paper in papers]
    status: dict[str, Any] = {
        "semanticscholar": {"enabled": False},
        "openalex": {"enabled": False},
    }

    if fetch_options.enable_semanticscholar:
        env_map = os.environ if env is None else env
        api_key = env_map.get(fetch_options.semanticscholar_api_key_env)
        client = SemanticScholarClient(api_key=api_key)
        enriched: list[Paper] = []
        success_count = 0
        for idx, paper in enumerate(cloned):
            before = json.dumps(paper.source_metadata.get("semanticscholar"), sort_keys=True, ensure_ascii=False)
            if idx < 40:
                paper = client.enrich_title(paper)
                time.sleep(sleep_s)
            after = json.dumps(paper.source_metadata.get("semanticscholar"), sort_keys=True, ensure_ascii=False)
            if before != after and paper.source_metadata.get("semanticscholar"):
                success_count += 1
            enriched.append(paper)
        cloned = enriched
        status["semanticscholar"] = {"enabled": True, "enriched": success_count}

    cloned, openalex_status = enrich_openalex(cloned, fetch_options, env=env, sleep_s=min(sleep_s, 0.2))
    status["openalex"] = openalex_status
    return deduplicate(cloned), status


def enrich_papers(
    papers: Iterable[Paper],
    fetch_options: FetchOptions,
    env: Mapping[str, str] | None = None,
    sleep_s: float = 0.5,
) -> list[Paper]:
    enriched, _ = enrich_papers_with_status(papers, fetch_options, env=env, sleep_s=sleep_s)
    return enriched


def assign_tracks(papers: Iterable[Paper], digest_options: DigestOptions) -> list[Paper]:
    assigned: list[Paper] = []
    ordered_tracks = list(digest_options.tracks)
    track_definitions = digest_options.track_definitions
    if TRACK_UNASSIGNED not in ordered_tracks:
        ordered_tracks = [*ordered_tracks, TRACK_UNASSIGNED]

    for paper in papers:
        candidate = clone_paper(paper)
        text = _paper_text(candidate)
        matches: list[str] = []
        reasons: dict[str, list[str]] = {}

        for track_id in ordered_tracks:
            definition = track_definitions.get(track_id, {"label": track_id, "keywords": []})
            keywords = parse_keywords_input(definition.get("keywords", []))
            if not keywords:
                continue
            hits = [keyword for keyword in keywords if keyword in text]
            if hits:
                matches.append(track_id)
                reasons[track_id] = hits

        if not matches:
            matches = [TRACK_UNASSIGNED]
            reasons[TRACK_UNASSIGNED] = []

        primary = next((track_id for track_id in ordered_tracks if track_id in matches), matches[0])
        candidate.track_ids = matches
        candidate.primary_track = primary
        candidate.track_reasons = reasons
        assigned.append(candidate)
    return assigned


def rank_papers(papers: Iterable[Paper], rank_options: RankOptions) -> list[Paper]:
    ranker = RuleRanker(rank_options)
    ranked = [ranker.score(clone_paper(paper)) for paper in papers]
    return sorted(ranked, key=lambda paper: paper.final_score, reverse=True)


def build_track_digest(
    papers: Sequence[Paper],
    digest_options: DigestOptions,
) -> TrackDigest:
    ranked = sorted([clone_paper(paper) for paper in papers], key=lambda item: item.final_score, reverse=True)

    ordered_tracks = [track for track in digest_options.tracks if track]
    if TRACK_UNASSIGNED not in ordered_tracks:
        ordered_tracks.append(TRACK_UNASSIGNED)

    top_papers = ranked[: digest_options.daily_top_k]
    daily_sections: list[dict[str, Any]] = []
    weekly_sections: list[dict[str, Any]] = []
    daily_lines = ["# Daily Paper Radar", ""]
    daily_lines.append("## Overall Top Picks")
    for idx, paper in enumerate(top_papers, start=1):
        daily_lines.extend(_digest_paper_lines(idx, paper))
    daily_lines.append("")

    for track_id in ordered_tracks:
        track_papers = [paper for paper in ranked if track_id in paper.track_ids]
        if not track_papers:
            continue
        preview = track_papers[: min(3, len(track_papers))]
        label = digest_options.track_definitions.get(track_id, {}).get("label", track_id)
        daily_lines.append(f"## {label}")
        daily_section = {"track_id": track_id, "label": label, "papers": preview}
        for idx, paper in enumerate(preview, start=1):
            daily_lines.append(
                f"- {idx}. {paper.title} ({paper.final_score:.2f}, {paper.bucket}, {paper.primary_track})"
            )
        daily_lines.append("")
        daily_sections.append(daily_section)

    weekly_lines = ["# Weekly Track Digest", ""]
    for track_id in ordered_tracks:
        track_papers = [paper for paper in ranked if paper.primary_track == track_id]
        if not track_papers:
            continue
        label = digest_options.track_definitions.get(track_id, {}).get("label", track_id)
        weekly_lines.append(f"## {label}")
        weekly_section = {"track_id": track_id, "label": label, "papers": []}
        for idx, paper in enumerate(track_papers[: digest_options.weekly_top_k_per_track], start=1):
            weekly_lines.extend(_digest_paper_lines(idx, paper))
            secondary = [track for track in paper.track_ids if track != track_id]
            if secondary:
                weekly_lines.append(f"- Secondary tracks: {', '.join(secondary)}")
            weekly_lines.append("")
            weekly_section["papers"].append(paper)
        weekly_sections.append(weekly_section)

    return TrackDigest(
        daily_markdown="\n".join(daily_lines).strip() + "\n",
        weekly_markdown="\n".join(weekly_lines).strip() + "\n",
        daily_sections=daily_sections,
        weekly_sections=weekly_sections,
    )


def build_markdown_digest(papers: list[Paper], top_k: int = 8) -> str:
    digest_options = DigestOptions(
        daily_top_k=top_k,
        weekly_top_k_per_track=max(1, min(top_k, 5)),
        tracks=[paper.primary_track for paper in papers if paper.primary_track] or [TRACK_UNASSIGNED],
        track_definitions=copy.deepcopy(BUILTIN_TRACK_DEFINITIONS),
    )
    return build_track_digest(papers, digest_options).daily_markdown


def export_results(
    papers: list[Paper],
    out_dir: str | Path,
    top_k: int,
    digest_options: DigestOptions | None = None,
) -> None:
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if digest_options is None:
        digest_options = DigestOptions(
            daily_top_k=top_k,
            weekly_top_k_per_track=max(1, min(top_k, 5)),
            tracks=[paper.primary_track for paper in papers if paper.primary_track] or [TRACK_UNASSIGNED],
            track_definitions=copy.deepcopy(BUILTIN_TRACK_DEFINITIONS),
        )
    digest_options = copy.deepcopy(digest_options)
    digest_options.daily_top_k = top_k
    track_digest = build_track_digest(papers, digest_options)
    (target_dir / "daily_radar.md").write_text(track_digest.daily_markdown, encoding="utf-8")
    (target_dir / "weekly_track_digest.md").write_text(track_digest.weekly_markdown, encoding="utf-8")
    (target_dir / "papers.jsonl").write_text(
        "\n".join(json.dumps(asdict(paper), ensure_ascii=False) for paper in papers),
        encoding="utf-8",
    )


def execute_pipeline(
    config: Mapping[str, Any],
    *,
    config_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    store_path: str | Path = DEFAULT_DB_PATH,
    out_dir: str | Path = "data",
    persist: bool = True,
    export: bool = True,
    pause_s: float = 3.0,
    sleep_s: float = 0.1,
) -> RunExecution:
    fetch_options = build_fetch_options_from_config(config)
    rank_options = build_rank_options_from_config(config)
    digest_options = build_digest_options_from_config(config)
    config_hash_value = config_hash(config)
    fetch_signature = fetch_options_signature(fetch_options)

    store = PaperRadarStore(store_path) if persist else None
    run_id = None
    if store is not None:
        run_id = store.start_run(
            config_hash_value=config_hash_value,
            config_path=str(config_path) if config_path is not None else None,
            config=config,
            fetch_signature=fetch_signature,
        )

    source_status: dict[str, Any] = {}
    try:
        fetched, collect_status = collect_papers(fetch_options, pause_s=pause_s)
        source_status.update(collect_status)
        enriched, enrich_status = enrich_papers_with_status(fetched, fetch_options, env=env, sleep_s=sleep_s)
        source_status.update(enrich_status)
        tracked = assign_tracks(enriched, digest_options)
        ranked = rank_papers(tracked, rank_options)
        track_digest = build_track_digest(ranked, digest_options)
        if store is not None and run_id is not None:
            store.persist_ranked_run(run_id, ranked)
            store.finalize_run(
                run_id,
                status="completed",
                total_papers=len(ranked),
                source_status=source_status,
                daily_digest=track_digest.daily_markdown,
                weekly_digest=track_digest.weekly_markdown,
            )
        if export:
            export_results(ranked, out_dir, top_k=rank_options.daily_top_k, digest_options=digest_options)
        return RunExecution(
            run_id=run_id,
            config_hash=config_hash_value,
            fetch_signature=fetch_signature,
            raw_papers=enriched,
            ranked_papers=ranked,
            source_status=source_status,
            daily_digest=track_digest.daily_markdown,
            weekly_digest=track_digest.weekly_markdown,
        )
    except Exception:
        if store is not None and run_id is not None:
            store.finalize_run(
                run_id,
                status="failed",
                total_papers=0,
                source_status=source_status,
            )
        raise


def run_radar(
    config_path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    store_path: str | Path = DEFAULT_DB_PATH,
    out_dir: str | Path = "data",
    persist: bool = True,
    export: bool = True,
) -> RunExecution:
    config = load_config(config_path)
    return execute_pipeline(
        config,
        config_path=config_path,
        env=env,
        store_path=store_path,
        out_dir=out_dir,
        persist=persist,
        export=export,
    )


def diff_configs(config_a: Mapping[str, Any], config_b: Mapping[str, Any]) -> dict[str, Any]:
    fetch_a = build_fetch_options_from_config(config_a)
    fetch_b = build_fetch_options_from_config(config_b)
    rank_a = build_rank_options_from_config(config_a)
    rank_b = build_rank_options_from_config(config_b)
    digest_a = build_digest_options_from_config(config_a)
    digest_b = build_digest_options_from_config(config_b)

    return {
        "fetch": {
            "queries_only_in_a": sorted(set(fetch_a.queries) - set(fetch_b.queries)),
            "queries_only_in_b": sorted(set(fetch_b.queries) - set(fetch_a.queries)),
            "categories_only_in_a": sorted(set(fetch_a.categories) - set(fetch_b.categories)),
            "categories_only_in_b": sorted(set(fetch_b.categories) - set(fetch_a.categories)),
            "days_back": {"a": fetch_a.days_back, "b": fetch_b.days_back},
            "openreview_venues_only_in_a": sorted(set(fetch_a.openreview_venues) - set(fetch_b.openreview_venues)),
            "openreview_venues_only_in_b": sorted(set(fetch_b.openreview_venues) - set(fetch_a.openreview_venues)),
        },
        "keywords": {
            "include_only_in_a": sorted(set(rank_a.include_keywords) - set(rank_b.include_keywords)),
            "include_only_in_b": sorted(set(rank_b.include_keywords) - set(rank_a.include_keywords)),
            "exclude_only_in_a": sorted(set(rank_a.exclude_keywords) - set(rank_b.exclude_keywords)),
            "exclude_only_in_b": sorted(set(rank_b.exclude_keywords) - set(rank_a.exclude_keywords)),
        },
        "weights": {
            key: {"a": round(rank_a.weights.get(key, 0.0), 6), "b": round(rank_b.weights.get(key, 0.0), 6)}
            for key in WEIGHT_KEYS
            if not math.isclose(rank_a.weights.get(key, 0.0), rank_b.weights.get(key, 0.0), abs_tol=1e-9)
        },
        "buckets": {
            key: {"a": rank_a.buckets.get(key), "b": rank_b.buckets.get(key)}
            for key in BUCKET_KEYS
            if not math.isclose(rank_a.buckets.get(key, 0.0), rank_b.buckets.get(key, 0.0), abs_tol=1e-9)
        },
        "ranking": {
            "openalex_priority_catalogs_only_in_a": sorted(
                set(rank_a.openalex_priority_catalogs) - set(rank_b.openalex_priority_catalogs)
            ),
            "openalex_priority_catalogs_only_in_b": sorted(
                set(rank_b.openalex_priority_catalogs) - set(rank_a.openalex_priority_catalogs)
            ),
        },
        "digest": {
            "tracks_only_in_a": sorted(set(digest_a.tracks) - set(digest_b.tracks)),
            "tracks_only_in_b": sorted(set(digest_b.tracks) - set(digest_a.tracks)),
            "track_definitions_changed": sorted(
                track_id
                for track_id in set(digest_a.track_definitions) | set(digest_b.track_definitions)
                if digest_a.track_definitions.get(track_id) != digest_b.track_definitions.get(track_id)
            ),
        },
    }


def compare_presets(
    preset_a_path: str | Path,
    preset_b_path: str | Path,
    *,
    store_path: str | Path = DEFAULT_DB_PATH,
    run_a_id: int | None = None,
    run_b_id: int | None = None,
) -> dict[str, Any]:
    config_a = load_config(preset_a_path)
    config_b = load_config(preset_b_path)
    store = PaperRadarStore(store_path)
    config_hash_a = config_hash(config_a)
    config_hash_b = config_hash(config_b)
    fetch_options_a = build_fetch_options_from_config(config_a)
    fetch_options_b = build_fetch_options_from_config(config_b)
    fetch_signature_a = fetch_options_signature(fetch_options_a)
    fetch_signature_b = fetch_options_signature(fetch_options_b)

    run_info_a = store.get_run(run_a_id) if run_a_id is not None else store.get_latest_run_by_config_hash(config_hash_a)
    run_info_b = store.get_run(run_b_id) if run_b_id is not None else store.get_latest_run_by_config_hash(config_hash_b)

    comparison: dict[str, Any] = {
        "config_diff": diff_configs(config_a, config_b),
        "raw_corpus_differs": fetch_signature_a != fetch_signature_b,
        "run_a": run_info_a,
        "run_b": run_info_b,
        "results": None,
    }

    papers_a: list[Paper] = []
    papers_b: list[Paper] = []

    if fetch_signature_a == fetch_signature_b:
        candidate_runs = [run for run in (run_info_a, run_info_b) if run is not None]
        if candidate_runs:
            base_run = max(candidate_runs, key=lambda run: run["id"])
            base_papers = store.load_run_papers(int(base_run["id"]))
            tracked_a = assign_tracks(base_papers, build_digest_options_from_config(config_a))
            tracked_b = assign_tracks(base_papers, build_digest_options_from_config(config_b))
            papers_a = rank_papers(tracked_a, build_rank_options_from_config(config_a))
            papers_b = rank_papers(tracked_b, build_rank_options_from_config(config_b))
            comparison["raw_corpus_differs"] = False
    else:
        if run_info_a is not None:
            papers_a = store.load_run_papers(int(run_info_a["id"]))
        if run_info_b is not None:
            papers_b = store.load_run_papers(int(run_info_b["id"]))

    if papers_a and papers_b:
        comparison["results"] = compare_ranked_lists(papers_a, papers_b)
    return comparison


def compare_ranked_lists(papers_a: Sequence[Paper], papers_b: Sequence[Paper], top_n: int = 10) -> dict[str, Any]:
    top_a = list(papers_a[:top_n])
    top_b = list(papers_b[:top_n])
    key_to_rank_a = {_comparison_key(paper): idx + 1 for idx, paper in enumerate(papers_a)}
    key_to_rank_b = {_comparison_key(paper): idx + 1 for idx, paper in enumerate(papers_b)}
    top_keys_a = {_comparison_key(paper) for paper in top_a}
    top_keys_b = {_comparison_key(paper) for paper in top_b}
    overlap_keys = top_keys_a & top_keys_b

    deltas: list[dict[str, Any]] = []
    all_keys = list(dict.fromkeys([*key_to_rank_a.keys(), *key_to_rank_b.keys()]))
    for key in all_keys:
        paper_a = next((paper for paper in papers_a if _comparison_key(paper) == key), None)
        paper_b = next((paper for paper in papers_b if _comparison_key(paper) == key), None)
        deltas.append(
            {
                "key": key,
                "title": (paper_a or paper_b).title if (paper_a or paper_b) else key,
                "rank_a": key_to_rank_a.get(key),
                "rank_b": key_to_rank_b.get(key),
                "rank_delta": _delta_or_none(key_to_rank_a.get(key), key_to_rank_b.get(key)),
                "score_a": paper_a.final_score if paper_a else None,
                "score_b": paper_b.final_score if paper_b else None,
                "score_delta": _float_delta(
                    paper_a.final_score if paper_a else None,
                    paper_b.final_score if paper_b else None,
                ),
                "bucket_a": paper_a.bucket if paper_a else None,
                "bucket_b": paper_b.bucket if paper_b else None,
                "primary_track_a": paper_a.primary_track if paper_a else None,
                "primary_track_b": paper_b.primary_track if paper_b else None,
            }
        )

    deltas.sort(key=lambda item: (item["rank_a"] or 9999, item["rank_b"] or 9999, item["title"]))
    return {
        "top_n": top_n,
        "top_overlap": len(overlap_keys),
        "only_in_a": [paper.title for paper in top_a if _comparison_key(paper) not in top_keys_b],
        "only_in_b": [paper.title for paper in top_b if _comparison_key(paper) not in top_keys_a],
        "deltas": deltas,
    }


def _comparison_key(paper: Paper) -> str:
    return paper.canonical_id or compute_canonical_key(paper)


def _delta_or_none(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return right - left


def _float_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(right - left, 2)


def _score_payload(paper: Paper) -> dict[str, Any]:
    return {
        "relevance": paper.relevance_score,
        "novelty": paper.novelty_score,
        "empirical": paper.empirical_score,
        "source_signal": paper.source_signal_score,
        "momentum": paper.momentum_score,
        "recency": paper.recency_score,
        "actionability": paper.actionability_score,
        "final": paper.final_score,
        "bucket": paper.bucket,
    }


def _paper_text(paper: Paper) -> str:
    parts = [
        paper.title,
        paper.abstract,
        " ".join(paper.categories),
        " ".join(paper.topics),
        paper.venue or "",
        paper.decision or "",
        " ".join(paper.track_ids),
        json.dumps(paper.source_metadata, ensure_ascii=False, sort_keys=True),
    ]
    return " ".join(part for part in parts if part).lower()


def _render_summary(summary_json: Mapping[str, Any]) -> str:
    fields = [
        ("?쒖쨪 ?붿빟", summary_json.get("summary")),
        ("??以묒슂?쒓?", summary_json.get("why_it_matters")),
        ("諛⑸쾿", summary_json.get("method")),
        ("?ㅽ뿕/寃곌낵", summary_json.get("setup_results")),
        ("robotics 愿?⑥꽦", summary_json.get("robotics_relevance")),
        ("?쒓퀎", summary_json.get("limitations")),
        ("愿?щ룄", summary_json.get("interest_score")),
        ("異붿쿇 ?≪뀡", summary_json.get("recommended_action")),
    ]
    lines = []
    for label, value in fields:
        if value in (None, "", []):
            continue
        lines.append(f"- {label}: {value}")
    return "\n".join(lines).strip()


def _digest_paper_lines(idx: int, paper: Paper) -> list[str]:
    lines = [f"### {idx}. {paper.title}"]
    lines.append(f"- Score: {paper.final_score:.2f} ({paper.bucket})")
    lines.append(f"- Source: {paper.source}")
    lines.append(f"- Track: {paper.primary_track or '-'}")
    if paper.venue:
        lines.append(f"- Venue: {paper.venue}")
    if paper.decision:
        lines.append(f"- Decision: {paper.decision}")
    abstract_preview = paper.abstract[:500].strip()
    suffix = "..." if len(paper.abstract) > 500 else ""
    lines.append(f"- Abstract: {abstract_preview}{suffix}")
    lines.append(f"- URL: {paper.url}")
    return lines


def _content_value(content: Mapping[str, Any], key: str) -> Any:
    if key not in content:
        return None
    value = content.get(key)
    if isinstance(value, Mapping):
        return value.get("value")
    return value


def _normalize_author_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _normalize_string_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return parse_keywords_input(value)
    if isinstance(value, Sequence):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _extract_numeric_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    return float(match.group(1)) if match else None


def _ms_to_iso(value: Any) -> str | None:
    if value in (None, "", 0):
        return None
    try:
        timestamp_ms = int(value)
    except (TypeError, ValueError):
        return None
    return dt.datetime.fromtimestamp(timestamp_ms / 1000, tz=dt.timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _parse_any_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        try:
            return dt.datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
