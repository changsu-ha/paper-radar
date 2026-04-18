from __future__ import annotations

import copy
import datetime as dt
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import requests

try:
    import yaml
except ModuleNotFoundError:
    yaml = None


ARXIV_API = "https://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
DEFAULT_CONFIG_PATH = Path("paper_radar_config.example.yaml")
DEFAULT_PRESET_DIR = Path("data/gui_presets")
DEFAULT_TIMEZONE = "Asia/Seoul"
DEFAULT_WARNING_LOG_PATH = Path("data/runtime_warnings.log")
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


@dataclass
class RankOptions:
    include_keywords: list[str]
    exclude_keywords: list[str]
    weights: dict[str, float]
    buckets: dict[str, float]
    daily_top_k: int


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if yaml is not None:
        return yaml.safe_load(text)
    return _load_simple_yaml(text)


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


def save_config(path: str | Path, config: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to save config files.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)


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


def paper_from_dict(data: Mapping[str, Any]) -> Paper:
    return Paper(**dict(data))


def clone_paper(paper: Paper) -> Paper:
    return paper_from_dict(asdict(paper))


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


def build_fetch_options_from_config(config: Mapping[str, Any]) -> FetchOptions:
    arxiv_cfg = config["sources"]["arxiv"]
    ss_cfg = config["sources"].get("semanticscholar", {})
    return FetchOptions(
        queries=[str(query).strip() for query in arxiv_cfg.get("queries", []) if str(query).strip()],
        categories=[str(cat).strip() for cat in arxiv_cfg.get("categories", []) if str(cat).strip()],
        days_back=int(arxiv_cfg.get("days_back_daily", 7)),
        max_results_per_query=int(arxiv_cfg.get("max_results_per_query", 100)),
        enable_semanticscholar=bool(ss_cfg.get("enabled", False)),
        semanticscholar_api_key_env=str(ss_cfg.get("api_key_env") or "SEMANTIC_SCHOLAR_API_KEY"),
    )


def build_rank_options_from_config(config: Mapping[str, Any]) -> RankOptions:
    return RankOptions(
        include_keywords=parse_keywords_input(config["filters"].get("include_keywords", [])),
        exclude_keywords=parse_keywords_input(config["filters"].get("exclude_keywords", [])),
        weights={key: float(config["ranking"]["weights"].get(key, 0.0)) for key in WEIGHT_KEYS},
        buckets={key: float(config["ranking"]["buckets"].get(key, 0.0)) for key in BUCKET_KEYS},
        daily_top_k=int(config["digest"].get("daily_top_k", 8)),
    )


def build_config_from_options(
    base_config: Mapping[str, Any],
    fetch_options: FetchOptions,
    rank_options: RankOptions,
) -> dict[str, Any]:
    config = copy.deepcopy(dict(base_config))
    config.setdefault("sources", {})
    config["sources"].setdefault("arxiv", {})
    config["sources"].setdefault("semanticscholar", {})
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
    config["filters"]["include_keywords"] = list(rank_options.include_keywords)
    config["filters"]["exclude_keywords"] = list(rank_options.exclude_keywords)
    config["ranking"]["weights"] = normalized_weights
    config["ranking"]["buckets"] = {key: float(rank_options.buckets.get(key, 0.0)) for key in BUCKET_KEYS}
    config["digest"]["daily_top_k"] = int(rank_options.daily_top_k)
    return config


def fetch_options_signature(fetch_options: FetchOptions) -> str:
    payload = {
        "queries": list(fetch_options.queries),
        "categories": list(fetch_options.categories),
        "days_back": int(fetch_options.days_back),
        "max_results_per_query": int(fetch_options.max_results_per_query),
        "enable_semanticscholar": bool(fetch_options.enable_semanticscholar),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def describe_keyword_hits(paper: Paper, rank_options: RankOptions) -> dict[str, list[str]]:
    text = f"{paper.title} {paper.abstract}".lower()
    include_hits = [kw for kw in rank_options.include_keywords if kw in text]
    exclude_hits = [kw for kw in rank_options.exclude_keywords if kw in text]
    return {
        "include_hits": include_hits,
        "exclude_hits": exclude_hits,
    }


def papers_to_records(papers: Iterable[Paper]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for paper in papers:
        records.append(
            {
                "title": paper.title,
                "final_score": paper.final_score,
                "bucket": paper.bucket,
                "published_at": paper.published_at,
                "categories": ", ".join(paper.categories),
                "citations": paper.citations,
                "source": paper.source,
                "url": paper.url,
            }
        )
    return records


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
        cat_clause = " OR ".join(f"cat:{c}" for c in categories)
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
        headers = {"User-Agent": "paper-radar-harness/0.1 (+research scout)"}
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
                    raw={"entry_id": entry_id},
                    normalized_title=normalize_title(title),
                )
            )
        return papers

    @staticmethod
    def _is_recent_enough(published_at: str | None, cutoff: dt.datetime) -> bool:
        if not published_at:
            return False
        try:
            published = dt.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return published >= cutoff


class SemanticScholarClient:
    """Optional metadata enricher. Expects an API key for heavy usage."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def enrich_title(self, paper: Paper) -> Paper:
        headers = {"User-Agent": "paper-radar-harness/0.1 (+research scout)"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        params = {
            "query": paper.title,
            "fields": "title,year,venue,citationCount,openAccessPdf,externalIds,fieldsOfStudy",
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
        best = data[0]
        paper.citations = best.get("citationCount")
        paper.venue = paper.venue or best.get("venue")
        fos = best.get("fieldsOfStudy") or []
        paper.topics = [str(x) for x in fos]
        ext = best.get("externalIds") or {}
        if not paper.doi and ext.get("DOI"):
            paper.doi = ext["DOI"]
        oa_pdf = best.get("openAccessPdf") or {}
        if not paper.pdf_url and oa_pdf.get("url"):
            paper.pdf_url = oa_pdf["url"]
        return paper


class RuleRanker:
    def __init__(self, rank_options: RankOptions) -> None:
        self.include_keywords = [kw.lower() for kw in rank_options.include_keywords]
        self.exclude_keywords = [kw.lower() for kw in rank_options.exclude_keywords]
        self.weights, _, _ = normalize_weight_map(rank_options.weights)
        self.buckets = rank_options.buckets

    def score(self, paper: Paper) -> Paper:
        text = f"{paper.title} {paper.abstract}".lower()
        relevance_hits = sum(1 for kw in self.include_keywords if kw in text)
        exclude_hits = sum(1 for kw in self.exclude_keywords if kw in text)

        paper.relevance_score = min(100.0, relevance_hits * 12.5)
        if "cs.ro" in [c.lower() for c in paper.categories]:
            paper.relevance_score = min(100.0, paper.relevance_score + 20.0)

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
        paper.source_signal_score = 20.0 if paper.source == "arxiv" else 0.0
        paper.momentum_score = (
            0.0 if paper.citations is None else min(100.0, math.log1p(paper.citations) * 20.0)
        )
        paper.recency_score = self._recency_score(paper.published_at)
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

    def _bucket(self, score: float) -> str:
        if score >= self.buckets.get("must_read", 85):
            return "must_read"
        if score >= self.buckets.get("worth_reading", 70):
            return "worth_reading"
        if score >= self.buckets.get("skim", 55):
            return "skim"
        return "archive"

    def _recency_score(self, published_at: str | None) -> float:
        if not published_at:
            return 20.0
        try:
            pub = dt.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            delta_days = max(0.0, (dt.datetime.now(dt.timezone.utc) - pub).days)
        except ValueError:
            return 20.0
        return max(0.0, 100.0 - delta_days * 3.0)


def deduplicate(papers: Iterable[Paper]) -> list[Paper]:
    seen: set[str] = set()
    out: list[Paper] = []
    for paper in papers:
        key = paper.doi or paper.external_id or paper.normalized_title or normalize_title(paper.title)
        if key in seen:
            continue
        seen.add(key)
        out.append(paper)
    return out


def fetch_papers(fetch_options: FetchOptions, pause_s: float = 3.0) -> list[Paper]:
    collector = ArxivClient(pause_s=pause_s)
    papers: list[Paper] = []
    for query in fetch_options.queries:
        batch = collector.search(
            query=query,
            categories=fetch_options.categories,
            days_back=fetch_options.days_back,
            max_results=fetch_options.max_results_per_query,
        )
        papers.extend(batch)
    return deduplicate(papers)


def enrich_papers(
    papers: Iterable[Paper],
    fetch_options: FetchOptions,
    env: Mapping[str, str] | None = None,
    sleep_s: float = 0.5,
) -> list[Paper]:
    cloned = [clone_paper(paper) for paper in papers]
    if not fetch_options.enable_semanticscholar:
        return cloned

    env_map = os.environ if env is None else env
    api_key = env_map.get(fetch_options.semanticscholar_api_key_env)
    client = SemanticScholarClient(api_key=api_key)

    enriched: list[Paper] = []
    for idx, paper in enumerate(cloned):
        if idx < 20:
            paper = client.enrich_title(paper)
            time.sleep(sleep_s)
        enriched.append(paper)
    return enriched


def rank_papers(papers: Iterable[Paper], rank_options: RankOptions) -> list[Paper]:
    ranker = RuleRanker(rank_options)
    ranked = [ranker.score(clone_paper(paper)) for paper in papers]
    return sorted(ranked, key=lambda paper: paper.final_score, reverse=True)


def build_markdown_digest(papers: list[Paper], top_k: int = 8) -> str:
    selected = sorted(papers, key=lambda paper: paper.final_score, reverse=True)[:top_k]
    lines = ["# Daily Paper Radar", ""]
    for idx, paper in enumerate(selected, 1):
        lines.append(f"## {idx}. {paper.title}")
        lines.append(f"- Source: {paper.source}")
        lines.append(f"- URL: {paper.url}")
        lines.append(f"- Categories: {', '.join(paper.categories)}")
        lines.append(f"- Score: {paper.final_score} ({paper.bucket})")
        lines.append(f"- Abstract: {paper.abstract[:700]}...")
        lines.append("")
    return "\n".join(lines)


def export_results(papers: list[Paper], out_dir: str | Path, top_k: int) -> None:
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = build_markdown_digest(papers, top_k=top_k)
    (target_dir / "daily_radar.md").write_text(digest, encoding="utf-8")
    (target_dir / "papers.jsonl").write_text(
        "\n".join(json.dumps(asdict(paper), ensure_ascii=False) for paper in papers),
        encoding="utf-8",
    )


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
