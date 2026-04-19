from __future__ import annotations

import copy
import datetime as dt
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping

try:
    import pandas as pd
except ModuleNotFoundError as exc:
    raise SystemExit(
        "pandas is required to run the GUI. Install dependencies with `pip install -r requirements.txt`."
    ) from exc

try:
    import streamlit as st
except ModuleNotFoundError as exc:
    raise SystemExit(
        "streamlit is required to run the GUI. Install dependencies with `pip install -r requirements.txt`."
    ) from exc

try:
    import yaml as runtime_yaml
except ModuleNotFoundError:
    runtime_yaml = None

from paper_radar_core import (
    BUCKET_KEYS,
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_PRESET_DIR,
    DigestOptions,
    FetchOptions,
    Paper,
    PaperRadarStore,
    RankOptions,
    TRACK_UNASSIGNED,
    WEIGHT_KEYS,
    assign_tracks,
    build_config_from_options,
    build_digest_options_from_config,
    build_fetch_options_from_config,
    build_rank_options_from_config,
    build_track_digest,
    compare_presets,
    config_hash,
    describe_keyword_hits,
    execute_pipeline,
    export_results,
    fetch_options_signature,
    get_config_path,
    is_openalex_affiliation_catalog_config,
    load_config,
    normalize_weight_map,
    openalex_self_check,
    paper_from_dict,
    papers_to_records,
    parse_keywords_input,
    rank_papers,
    save_config,
    split_multiline_list,
)


CATEGORY_OPTIONS = [
    "cs.RO",
    "cs.LG",
    "cs.AI",
    "cs.CV",
    "cs.CL",
    "cs.GR",
    "cs.HC",
    "cs.IR",
    "stat.ML",
]

RESET_SESSION_KEYS = (
    "fetched_raw_papers",
    "last_fetch_signature",
    "last_fetch_at",
    "last_fetch_count",
    "last_run_id",
    "last_source_status",
    "selected_paper_label",
    "last_comparison",
    "compare_config_a",
    "compare_config_b",
    "compare_run_a",
    "compare_run_b",
    "openalex_self_check_result",
)

FIELD_HELP = {
    "config_selector": "실험의 시작점이 되는 YAML 설정 파일입니다. 불러오면 현재 세션의 fetch 결과와 비교 상태를 초기화합니다.",
    "preset_name": "현재 화면 설정을 data/gui_presets/<name>.yaml 로 저장할 때 사용할 이름입니다.",
    "days_back": "최근 며칠 안에 나온 논문만 수집할지 정합니다. 숫자가 작을수록 최신 논문만 봅니다.",
    "max_results_per_query": "각 query에서 최대 몇 편까지 가져올지 정합니다. 값이 클수록 더 넓게 수집하지만 속도는 느려집니다.",
    "queries_text": "arXiv 검색식입니다. 줄마다 하나의 query로 처리됩니다.",
    "categories": "arXiv 카테고리 필터입니다. query와 함께 적용됩니다.",
    "enable_semanticscholar": "Semantic Scholar에서 citation, venue, field 정보를 추가로 붙입니다. 후보 논문 수를 늘리는 기능은 아니고 메타데이터 enrich입니다.",
    "enable_openreview": "OpenReview에서 venue 단위로 논문을 추가 수집합니다. arXiv와 별도 source입니다.",
    "openreview_venues_text": "OpenReview venue id 목록입니다. 줄마다 하나씩 입력합니다.",
    "openreview_keywords_text": "OpenReview 수집 결과 중 제목/초록/키워드에 들어 있어야 할 필터 키워드입니다. 쉼표 또는 줄바꿈으로 구분합니다.",
    "enable_openalex": "OpenAlex에서 citation, topic, OA 정보를 추가로 붙입니다. 후보 논문 수를 늘리는 기능은 아니고 메타데이터 enrich입니다.",
    "openalex_priority_catalogs": "OpenAlex affiliation 기준으로 우선 순위를 올릴 기관 catalog입니다. 선택한 catalog와 저자 소속 기관이 매칭되면 source_signal bonus가 붙습니다.",
    "include_keywords_text": "이 키워드가 논문 텍스트에 많이 등장할수록 relevance 점수가 올라갑니다.",
    "exclude_keywords_text": "이 키워드가 발견되면 해당 논문은 바로 archive 처리됩니다.",
    "daily_top_k": "daily digest와 export에서 앞쪽에 보여줄 상위 논문 수입니다.",
    "weekly_top_k_per_track": "weekly digest에서 track별로 보여줄 최대 논문 수입니다.",
    "digest_tracks_text": "track 우선순서입니다. 여러 track에 동시에 걸리면 먼저 나온 track이 primary track이 됩니다.",
    "track_definitions_text": "기본 track 정의를 덮어쓰는 YAML입니다. label과 keywords를 직접 지정할 수 있습니다.",
}

WEIGHT_HELP = {
    "relevance": "내가 보고 싶은 주제와 얼마나 직접적으로 맞는지입니다. include_keywords, 카테고리, primary track이 주로 반영됩니다.",
    "novelty": "새로운 문제 설정, 방법, benchmark, dataset 같은 새로움 신호입니다.",
    "empirical": "ablation, baseline, simulation, real-world 같은 실험과 검증 신호입니다.",
    "source_signal": "출처와 메타데이터 품질 신호입니다. arXiv/OpenReview 존재, accept 여부, review signal, venue, OA 정보가 반영됩니다.",
    "momentum": "citation 기반 영향력입니다. citation 수가 많을수록 높아지지만 log 스케일이라 급격히 커지지는 않습니다.",
    "recency": "최신성입니다. 최근 논문일수록 점수가 높습니다.",
    "actionability": "실제로 읽고 적용할 만한 실용성 신호입니다. robot, policy, world model 같은 행동 지향 키워드가 반영됩니다.",
}

BUCKET_HELP = {
    "must_read": "이 점수 이상이면 반드시 읽을 논문으로 분류합니다.",
    "worth_reading": "이 점수 이상이면 worth_reading으로 분류합니다.",
    "skim": "이 점수 이상이면 skim으로 분류합니다. 그 아래는 archive입니다.",
}


def main() -> None:
    st.set_page_config(page_title="Paper Radar GUI", layout="wide")

    initial_config_path = get_runtime_config_path()
    initialize_session(initial_config_path)
    discovered_configs = discover_config_yaml_paths(extra_paths=[Path(st.session_state["config_source_path"])])
    discovered_catalogs = discover_priority_catalog_paths()
    current_config_path = Path(st.session_state["config_source_path"])
    current_config_label = label_for_path(discovered_configs, current_config_path)
    store = PaperRadarStore(DEFAULT_DB_PATH)

    st.title("Paper Radar GUI")
    st.caption(f"현재 YAML: `{current_config_path}`")
    st.caption(f"SQLite: `{DEFAULT_DB_PATH}`")

    with st.sidebar:
        render_sidebar(discovered_configs, discovered_catalogs, current_config_label)

    fetch_options = build_fetch_options_from_session()
    rank_options = build_rank_options_from_session()
    digest_options = build_digest_options_from_session()
    current_config = build_config_from_options(
        st.session_state["config_template"],
        fetch_options,
        rank_options,
        digest_options,
    )
    current_fetch_signature = fetch_options_signature(fetch_options)
    needs_refetch = (
        bool(st.session_state.get("fetched_raw_papers"))
        and st.session_state.get("last_fetch_signature") != current_fetch_signature
    )

    show_top_controls(fetch_options, rank_options, needs_refetch)

    button_cols = st.columns([1, 1, 1, 2])
    if button_cols[0].button("Fetch", type="primary", use_container_width=True):
        run_fetch(current_config, current_config_path, current_fetch_signature)
        needs_refetch = False
    if button_cols[1].button("Export", use_container_width=True):
        ranked_now = rank_current_session_papers(rank_options, digest_options)
        export_results(
            ranked_now,
            Path("data"),
            top_k=rank_options.daily_top_k,
            digest_options=digest_options,
        )
        st.success("현재 결과를 data/ 아래 digest와 papers.jsonl로 저장했습니다.")
    button_cols[2].download_button(
        label="현재 YAML 다운로드",
        data=serialize_config(current_config),
        file_name="paper_radar_gui_config.yaml",
        mime="text/yaml",
        use_container_width=True,
    )
    if st.session_state.get("last_run_id"):
        button_cols[3].caption(
            f"마지막 run: `#{st.session_state['last_run_id']}` / fetch 시각: {format_fetch_time(st.session_state.get('last_fetch_at'))}"
        )

    ranked_papers = rank_current_session_papers(rank_options, digest_options)
    show_metrics(ranked_papers)

    tabs = st.tabs(["Single Run", "Track Digest", "Compare"])
    with tabs[0]:
        render_single_run_tab(ranked_papers, rank_options)
    with tabs[1]:
        render_digest_tab(ranked_papers, digest_options)
    with tabs[2]:
        render_compare_tab(store, discovered_configs)


def get_runtime_config_path() -> Path:
    return get_config_path()


def discover_config_yaml_paths(
    *,
    repo_root: Path | None = None,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    preset_dir: Path = DEFAULT_PRESET_DIR,
    extra_paths: Iterable[Path] = (),
) -> dict[str, Path]:
    root = (repo_root or Path(".")).resolve()
    config_root = (root / config_dir).resolve() if not Path(config_dir).is_absolute() else Path(config_dir).resolve()
    preset_root = (root / preset_dir).resolve() if not Path(preset_dir).is_absolute() else Path(preset_dir).resolve()
    paths: list[Path] = []

    if config_root.exists():
        for pattern in ("*.yaml", "*.yml"):
            for path in sorted(config_root.glob(pattern)):
                if is_catalog_yaml_path(path):
                    continue
                paths.append(path.resolve())

    if preset_root.exists():
        for pattern in ("*.yaml", "*.yml"):
            for path in sorted(preset_root.glob(pattern)):
                paths.append(path.resolve())

    for extra_path in extra_paths:
        candidate = Path(extra_path).expanduser().resolve()
        if candidate.suffix.lower() != ".yaml":
            continue
        if is_catalog_yaml_path(candidate):
            continue
        paths.append(candidate)

    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        unique_paths.append(path)

    labeled: dict[str, Path] = {}
    for path in unique_paths:
        label = build_config_label(path, root=root, config_root=config_root, preset_root=preset_root)
        if label in labeled:
            label = f"{label} [{path.parent.name}]"
        labeled[label] = path
    return labeled


def discover_priority_catalog_paths(
    *,
    repo_root: Path | None = None,
    config_dir: Path = DEFAULT_CONFIG_DIR,
) -> dict[str, Path]:
    root = (repo_root or Path(".")).resolve()
    config_root = (root / config_dir).resolve() if not Path(config_dir).is_absolute() else Path(config_dir).resolve()
    labeled: dict[str, Path] = {}
    if not config_root.exists():
        return labeled

    for pattern in ("*.yaml", "*.yml"):
        for path in sorted(config_root.glob(pattern)):
            if not is_catalog_yaml_path(path):
                continue
            payload = load_yaml_payload(path)
            catalog_name = str(payload.get("catalog_name") or path.stem).strip()
            label = f"catalog: {catalog_name}"
            if label in labeled:
                label = f"{label} [{path.stem}]"
            labeled[label] = path.resolve()
    return labeled


def load_yaml_payload(path: Path) -> dict[str, Any]:
    try:
        payload = load_config(path)
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def is_catalog_yaml_path(path: Path) -> bool:
    payload = load_yaml_payload(path)
    return is_openalex_affiliation_catalog_config(payload)


def build_config_label(path: Path, *, root: Path, config_root: Path, preset_root: Path) -> str:
    resolved = path.resolve()
    if resolved == DEFAULT_CONFIG_PATH.resolve():
        return f"{resolved.name}"
    try:
        if resolved.is_relative_to(config_root):
            return f"config: {resolved.stem}"
    except ValueError:
        pass
    try:
        if resolved.is_relative_to(preset_root):
            return f"preset: {resolved.stem}"
    except ValueError:
        pass
    try:
        if resolved.is_relative_to(root):
            return str(resolved.relative_to(root))
    except ValueError:
        pass
    return resolved.name


def build_catalog_option_labels(catalog_paths: Mapping[str, Path]) -> dict[str, str]:
    option_labels: dict[str, str] = {}
    for label, path in catalog_paths.items():
        option_labels[repo_relative_path(path)] = label
    return option_labels


def repo_relative_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path(".").resolve())).replace("\\", "/")
    except ValueError:
        return str(resolved)


def label_for_path(paths: Mapping[str, Path], target: Path) -> str:
    resolved_target = target.resolve()
    for label, path in paths.items():
        if path.resolve() == resolved_target:
            return label
    return next(iter(paths))


def initialize_session(config_path: Path) -> None:
    if st.session_state.get("initialized"):
        existing_path = st.session_state.get("config_source_path")
        if existing_path:
            candidate = Path(existing_path).expanduser()
            if candidate.exists():
                return

    resolved = config_path.expanduser().resolve()
    config = load_config(resolved)
    st.session_state["initialized"] = True
    st.session_state["config_source_path"] = str(resolved)
    st.session_state["config_template"] = copy.deepcopy(config)
    reset_session_state_for_config(st.session_state)
    apply_config_to_session(config)


def reset_session_state_for_config(state: MutableMapping[str, Any]) -> None:
    for key in RESET_SESSION_KEYS:
        state.pop(key, None)
    state["fetched_raw_papers"] = []
    state["last_fetch_signature"] = None
    state["last_fetch_at"] = None
    state["last_fetch_count"] = 0
    state["last_run_id"] = None
    state["last_source_status"] = {}
    state["selected_paper_label"] = ""
    state["last_comparison"] = None
    state["openalex_self_check_result"] = None
    state["preset_name"] = ""


def load_yaml_into_session(path: Path) -> None:
    config = load_config(path)
    st.session_state["config_source_path"] = str(path.resolve())
    st.session_state["config_template"] = copy.deepcopy(config)
    reset_session_state_for_config(st.session_state)
    apply_config_to_session(config)


def render_sidebar(
    discovered_configs: Mapping[str, Path],
    discovered_catalogs: Mapping[str, Path],
    current_label: str,
) -> None:
    st.header("YAML 선택")
    labels = list(discovered_configs.keys())
    if st.session_state.get("config_selector") not in labels:
        st.session_state["config_selector"] = current_label if current_label in labels else labels[0]
    st.selectbox(
        "YAML 파일",
        labels,
        key="config_selector",
        help=FIELD_HELP["config_selector"],
    )
    if st.button("불러오기", use_container_width=True):
        load_yaml_into_session(discovered_configs[st.session_state["config_selector"]])
        st.rerun()

    with st.expander("항목 설명", expanded=False):
        st.markdown(
            """
`Semantic Scholar enrich`와 `OpenAlex enrich`는 새 논문을 더 모으는 옵션이 아니라, 이미 수집한 논문에 citation, venue, topic, OA 같은 메타데이터를 추가로 붙이는 옵션입니다.

`weight.*`는 source별 weight가 아니라 최종 점수의 평가축 가중치입니다. source는 주로 `source_signal`, `momentum`, 그리고 enrich된 메타데이터를 통해 간접 반영됩니다.
"""
        )
        st.markdown("**weight 의미**")
        for key in WEIGHT_KEYS:
            st.markdown(f"- `weight.{key}`: {WEIGHT_HELP[key]}")

    st.divider()
    st.header("Preset 저장")
    st.text_input("저장 이름", key="preset_name", help=FIELD_HELP["preset_name"])
    if st.button("현재 설정 저장", use_container_width=True):
        preset_name = st.session_state["preset_name"].strip()
        if not preset_name:
            st.error("저장할 preset 이름을 입력하세요.")
        else:
            save_current_preset(preset_name)
            st.success(f"`{preset_name}` preset을 저장했습니다.")

    st.divider()
    st.header("Fetch 설정")
    st.number_input(
        "검색 기간 (days_back)",
        min_value=1,
        max_value=365,
        key="days_back",
        help=FIELD_HELP["days_back"],
    )
    st.number_input(
        "query별 최대 결과 수",
        min_value=1,
        max_value=500,
        key="max_results_per_query",
        help=FIELD_HELP["max_results_per_query"],
    )
    st.text_area(
        "arXiv queries",
        height=140,
        key="queries_text",
        help=FIELD_HELP["queries_text"],
    )
    category_options = sorted(set(CATEGORY_OPTIONS + st.session_state.get("categories", [])))
    st.multiselect("카테고리", category_options, key="categories", help=FIELD_HELP["categories"])
    st.toggle(
        "Semantic Scholar enrich",
        key="enable_semanticscholar",
        help=FIELD_HELP["enable_semanticscholar"],
    )
    st.toggle(
        "OpenReview 수집",
        key="enable_openreview",
        help=FIELD_HELP["enable_openreview"],
    )
    st.text_area(
        "OpenReview venues",
        height=90,
        key="openreview_venues_text",
        help=FIELD_HELP["openreview_venues_text"],
    )
    st.text_area(
        "OpenReview keywords",
        height=90,
        key="openreview_keywords_text",
        help=FIELD_HELP["openreview_keywords_text"],
    )
    st.toggle("OpenAlex enrich", key="enable_openalex", help=FIELD_HELP["enable_openalex"])
    catalog_option_labels = build_catalog_option_labels(discovered_catalogs)
    current_catalogs = [
        str(path).strip()
        for path in st.session_state.get("openalex_priority_catalogs", [])
        if str(path).strip()
    ]
    for catalog_path in current_catalogs:
        catalog_option_labels.setdefault(catalog_path, f"catalog: {Path(catalog_path).stem}")
    st.multiselect(
        "OpenAlex priority catalogs",
        options=list(catalog_option_labels.keys()),
        key="openalex_priority_catalogs",
        help=FIELD_HELP["openalex_priority_catalogs"],
        format_func=lambda item: catalog_option_labels.get(item, item),
    )
    if st.session_state.get("openalex_priority_catalogs") and not st.session_state.get("enable_openalex"):
        st.warning("OpenAlex priority catalog를 선택했지만 현재 `OpenAlex enrich`가 꺼져 있습니다.")
    if st.button("OpenAlex self-check", use_container_width=True):
        st.session_state["openalex_self_check_result"] = run_openalex_self_check_from_session()
    render_openalex_self_check_result(st.session_state.get("openalex_self_check_result"))

    st.divider()
    st.header("Ranking 설정")
    st.text_area(
        "include_keywords",
        height=120,
        key="include_keywords_text",
        help=FIELD_HELP["include_keywords_text"],
    )
    st.text_area(
        "exclude_keywords",
        height=80,
        key="exclude_keywords_text",
        help=FIELD_HELP["exclude_keywords_text"],
    )
    for weight_key in WEIGHT_KEYS:
        st.number_input(
            f"weight.{weight_key}",
            min_value=0.0,
            step=0.01,
            format="%.4f",
            key=f"weight_{weight_key}",
            help=WEIGHT_HELP[weight_key],
        )
    for bucket_key in BUCKET_KEYS:
        st.number_input(
            f"bucket.{bucket_key}",
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            format="%.1f",
            key=f"bucket_{bucket_key}",
            help=BUCKET_HELP[bucket_key],
        )

    st.divider()
    st.header("Digest 설정")
    st.number_input(
        "daily_top_k",
        min_value=1,
        max_value=100,
        key="daily_top_k",
        help=FIELD_HELP["daily_top_k"],
    )
    st.number_input(
        "weekly_top_k_per_track",
        min_value=1,
        max_value=50,
        key="weekly_top_k_per_track",
        help=FIELD_HELP["weekly_top_k_per_track"],
    )
    st.text_area(
        "track order",
        height=120,
        key="digest_tracks_text",
        help=FIELD_HELP["digest_tracks_text"],
    )
    st.text_area(
        "custom track_definitions (YAML)",
        height=160,
        key="track_definitions_text",
        help=FIELD_HELP["track_definitions_text"],
    )


def apply_config_to_session(config: Mapping[str, Any]) -> None:
    fetch_options = build_fetch_options_from_config(config)
    rank_options = build_rank_options_from_config(config)
    digest_options = build_digest_options_from_config(config)
    normalized_weights, _, _ = normalize_weight_map(rank_options.weights)

    st.session_state["days_back"] = int(fetch_options.days_back)
    st.session_state["max_results_per_query"] = int(fetch_options.max_results_per_query)
    st.session_state["queries_text"] = "\n".join(fetch_options.queries)
    st.session_state["categories"] = list(fetch_options.categories)
    st.session_state["enable_semanticscholar"] = bool(fetch_options.enable_semanticscholar)
    st.session_state["enable_openreview"] = bool(fetch_options.enable_openreview)
    st.session_state["openreview_venues_text"] = "\n".join(fetch_options.openreview_venues)
    st.session_state["openreview_keywords_text"] = "\n".join(fetch_options.openreview_keywords)
    st.session_state["enable_openalex"] = bool(fetch_options.enable_openalex)
    st.session_state["openalex_priority_catalogs"] = list(rank_options.openalex_priority_catalogs)
    st.session_state["include_keywords_text"] = "\n".join(rank_options.include_keywords)
    st.session_state["exclude_keywords_text"] = "\n".join(rank_options.exclude_keywords)
    for weight_key in WEIGHT_KEYS:
        st.session_state[f"weight_{weight_key}"] = float(normalized_weights[weight_key])
    for bucket_key in BUCKET_KEYS:
        st.session_state[f"bucket_{bucket_key}"] = float(rank_options.buckets.get(bucket_key, 0.0))
    st.session_state["daily_top_k"] = int(digest_options.daily_top_k)
    st.session_state["weekly_top_k_per_track"] = int(digest_options.weekly_top_k_per_track)
    st.session_state["digest_tracks_text"] = "\n".join(digest_options.tracks)
    st.session_state["track_definitions_text"] = serialize_track_definitions(digest_options)


def build_fetch_options_from_session() -> FetchOptions:
    template = st.session_state["config_template"]
    sources = template.get("sources", {})
    semantic_env = sources.get("semanticscholar", {}).get("api_key_env", "SEMANTIC_SCHOLAR_API_KEY")
    openalex_env = sources.get("openalex", {}).get("api_key_env", "OPENALEX_API_KEY")
    return FetchOptions(
        queries=split_multiline_list(st.session_state["queries_text"]),
        categories=[str(item).strip() for item in st.session_state["categories"] if str(item).strip()],
        days_back=int(st.session_state["days_back"]),
        max_results_per_query=int(st.session_state["max_results_per_query"]),
        enable_semanticscholar=bool(st.session_state["enable_semanticscholar"]),
        semanticscholar_api_key_env=str(semantic_env),
        enable_openreview=bool(st.session_state["enable_openreview"]),
        openreview_venues=split_multiline_list(st.session_state["openreview_venues_text"]),
        openreview_keywords=parse_keywords_input(st.session_state["openreview_keywords_text"]),
        enable_openalex=bool(st.session_state["enable_openalex"]),
        openalex_api_key_env=str(openalex_env),
    )


def build_rank_options_from_session() -> RankOptions:
    weights = {weight_key: float(st.session_state[f"weight_{weight_key}"]) for weight_key in WEIGHT_KEYS}
    buckets = {bucket_key: float(st.session_state[f"bucket_{bucket_key}"]) for bucket_key in BUCKET_KEYS}
    return RankOptions(
        include_keywords=parse_keywords_input(st.session_state["include_keywords_text"]),
        exclude_keywords=parse_keywords_input(st.session_state["exclude_keywords_text"]),
        weights=weights,
        buckets=buckets,
        daily_top_k=int(st.session_state["daily_top_k"]),
        openalex_priority_catalogs=[
            str(path).strip()
            for path in st.session_state.get("openalex_priority_catalogs", [])
            if str(path).strip()
        ],
    )


def run_openalex_self_check_from_session(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    fetch_options = build_fetch_options_from_session()
    result = openalex_self_check(fetch_options.openalex_api_key_env, env=env)
    result["enabled"] = bool(fetch_options.enable_openalex)
    result["api_key_env"] = fetch_options.openalex_api_key_env
    return result


def render_openalex_self_check_result(result: Mapping[str, Any] | None) -> None:
    if not result:
        return

    enabled = bool(result.get("enabled"))
    env_present = bool(result.get("env_present"))
    http_ok = bool(result.get("http_ok"))
    if http_ok:
        st.success("OpenAlex self-check passed.")
    elif env_present:
        st.error(str(result.get("message") or "OpenAlex self-check failed."))
    else:
        st.warning(str(result.get("message") or "OpenAlex API key is missing."))

    if not enabled:
        st.info("현재 GUI 세션에서 `OpenAlex enrich`가 꺼져 있습니다. YAML을 다시 불러왔는지 확인하세요.")

    st.caption(
        " / ".join(
            [
                f"enabled={enabled}",
                f"env={result.get('api_key_env')}",
                f"source={result.get('env_source') or '-'}",
                f"masked={result.get('api_key_masked') or '-'}",
            ]
        )
    )
    st.json(
        {
            "openalex_enabled": enabled,
            "env_present": env_present,
            "http_ok": http_ok,
            "env_source": result.get("env_source"),
            "status_code": result.get("status_code"),
            "daily_remaining_usd": result.get("daily_remaining_usd"),
            "resets_at": result.get("resets_at"),
            "message": result.get("message"),
        }
    )


def build_digest_options_from_session() -> DigestOptions:
    base = build_digest_options_from_config(st.session_state["config_template"])
    tracks = split_multiline_list(st.session_state["digest_tracks_text"])
    definitions = copy.deepcopy(base.track_definitions)
    custom_definitions = parse_track_definitions_text(st.session_state["track_definitions_text"])
    for track_id, definition in custom_definitions.items():
        definitions[str(track_id)] = {
            "label": str(definition.get("label", track_id)),
            "keywords": parse_keywords_input(definition.get("keywords", [])),
        }
    if TRACK_UNASSIGNED not in definitions:
        definitions[TRACK_UNASSIGNED] = {"label": "Unassigned", "keywords": []}
    return DigestOptions(
        daily_top_k=int(st.session_state["daily_top_k"]),
        weekly_top_k_per_track=int(st.session_state["weekly_top_k_per_track"]),
        tracks=tracks or base.tracks,
        track_definitions=definitions,
    )


def run_fetch(current_config: Mapping[str, Any], config_path: Path, current_fetch_signature: str) -> None:
    try:
        with st.spinner("논문을 수집하고 enrich 및 ranking을 수행하는 중입니다..."):
            execution = execute_pipeline(
                current_config,
                config_path=config_path,
                store_path=DEFAULT_DB_PATH,
                out_dir="data",
                persist=True,
                export=False,
            )
    except Exception as exc:
        st.error(f"Fetch 실행 중 오류가 발생했습니다: {exc}")
        return

    st.session_state["fetched_raw_papers"] = [asdict(paper) for paper in execution.raw_papers]
    st.session_state["last_fetch_signature"] = current_fetch_signature
    st.session_state["last_fetch_at"] = dt.datetime.now().isoformat()
    st.session_state["last_fetch_count"] = len(execution.raw_papers)
    st.session_state["last_run_id"] = execution.run_id
    st.session_state["last_source_status"] = execution.source_status
    st.session_state["selected_paper_label"] = ""
    if not execution.ranked_papers:
        st.warning("수집된 논문이 없습니다. query, 기간, source 설정을 다시 확인하세요.")
    else:
        st.success(f"{len(execution.ranked_papers)}편을 가져왔습니다. run_id={execution.run_id}")


def rank_current_session_papers(rank_options: RankOptions, digest_options: DigestOptions) -> list[Paper]:
    raw_papers = st.session_state.get("fetched_raw_papers", [])
    if not raw_papers:
        return []
    papers = [paper_from_dict(item) for item in raw_papers]
    tracked = assign_tracks(papers, digest_options)
    return rank_papers(tracked, rank_options)


def save_current_preset(name: str) -> None:
    fetch_options = build_fetch_options_from_session()
    rank_options = build_rank_options_from_session()
    digest_options = build_digest_options_from_session()
    config = build_config_from_options(
        st.session_state["config_template"],
        fetch_options,
        rank_options,
        digest_options,
    )
    save_config(DEFAULT_PRESET_DIR / f"{reformat_preset_name(name)}.yaml", config)


def show_top_controls(fetch_options: FetchOptions, rank_options: RankOptions, needs_refetch: bool) -> None:
    normalized_weights, raw_sum, normalized = normalize_weight_map(rank_options.weights)
    weight_line = ", ".join(f"{key}={value:.3f}" for key, value in normalized_weights.items())
    st.caption(f"현재 weight 합계: {raw_sum:.4f}")
    if normalized:
        st.warning(f"weight 합계가 1.0이 아니어서 정규화를 적용 중입니다. {weight_line}")
    else:
        st.caption(f"정규화된 weights: {weight_line}")

    if needs_refetch:
        st.warning("Fetch 관련 설정이 바뀌었습니다. 현재 표는 이전 fetch 기준이고, 다시 Fetch 해야 반영됩니다.")
    else:
        st.caption("현재 fetch 설정과 저장된 snapshot이 일치합니다.")

    if rank_options.openalex_priority_catalogs:
        raw_papers = st.session_state.get("fetched_raw_papers", [])
        has_openalex_institutions = any(
            ((paper.get("source_metadata") or {}).get("openalex") or {}).get("institutions")
            for paper in raw_papers
        )
        if not fetch_options.enable_openalex:
            st.warning("OpenAlex priority catalog가 선택되어 있지만 현재 `OpenAlex enrich`가 꺼져 있습니다. 다시 Fetch해야 bonus가 적용됩니다.")
        elif raw_papers and not has_openalex_institutions:
            st.warning("현재 snapshot에는 OpenAlex affiliation metadata가 없습니다. `OpenAlex enrich`를 켠 뒤 다시 Fetch해야 기관 우선 선별이 적용됩니다.")


def show_metrics(ranked_papers: list[Paper]) -> None:
    total_count = len(ranked_papers)
    must_read_count = sum(1 for paper in ranked_papers if paper.bucket == "must_read")
    top_score = ranked_papers[0].final_score if ranked_papers else 0.0
    metric_cols = st.columns(5)
    metric_cols[0].metric("총 논문 수", total_count)
    metric_cols[1].metric("Must Read", must_read_count)
    metric_cols[2].metric("최고 점수", f"{top_score:.2f}")
    metric_cols[3].metric("최근 Fetch", format_fetch_time(st.session_state.get("last_fetch_at")))
    metric_cols[4].metric("마지막 run", st.session_state.get("last_run_id") or "-")


def render_single_run_tab(ranked_papers: list[Paper], rank_options: RankOptions) -> None:
    if not ranked_papers:
        st.info("아직 fetch 결과가 없습니다. 설정을 조정한 뒤 Fetch를 실행하세요.")
        return

    if st.session_state.get("last_source_status"):
        with st.expander("Source 상태"):
            st.json(st.session_state["last_source_status"])

    dataframe = pd.DataFrame(papers_to_records(ranked_papers))
    st.subheader("결과 테이블")
    st.dataframe(dataframe, use_container_width=True, hide_index=True)

    options = [f"{idx + 1}. {paper.title}" for idx, paper in enumerate(ranked_papers)]
    if st.session_state.get("selected_paper_label") not in options:
        st.session_state["selected_paper_label"] = options[0]
    st.selectbox("상세 보기", options, key="selected_paper_label")
    selected_idx = options.index(st.session_state["selected_paper_label"])
    show_paper_detail(ranked_papers[selected_idx], rank_options)


def render_digest_tab(ranked_papers: list[Paper], digest_options: DigestOptions) -> None:
    if not ranked_papers:
        st.info("먼저 Fetch를 실행하면 track digest를 볼 수 있습니다.")
        return

    track_digest = build_track_digest(ranked_papers, digest_options)
    digest_cols = st.columns(2)
    with digest_cols[0]:
        st.subheader("Daily Digest")
        st.markdown(track_digest.daily_markdown)
    with digest_cols[1]:
        st.subheader("Weekly Track Digest")
        st.markdown(track_digest.weekly_markdown)


def render_compare_tab(store: PaperRadarStore, config_paths: Mapping[str, Path]) -> None:
    st.subheader("Config Compare")
    labels = list(config_paths.keys())
    if len(labels) < 2:
        st.info("비교하려면 YAML config가 두 개 이상 필요합니다.")
        return

    current_path = Path(st.session_state["config_source_path"]).resolve()
    default_a = label_for_path(config_paths, current_path)
    default_b = labels[1] if len(labels) > 1 and labels[0] == default_a else labels[0]
    if default_b == default_a and len(labels) > 1:
        default_b = labels[1]

    if st.session_state.get("compare_config_a") not in labels:
        st.session_state["compare_config_a"] = default_a
    if st.session_state.get("compare_config_b") not in labels:
        st.session_state["compare_config_b"] = default_b

    compare_cols = st.columns(2)
    label_a = compare_cols[0].selectbox("Config A", labels, key="compare_config_a")
    label_b = compare_cols[1].selectbox("Config B", labels, key="compare_config_b")

    path_a = config_paths[label_a]
    path_b = config_paths[label_b]
    config_a = load_config(path_a)
    config_b = load_config(path_b)
    hash_a = config_hash(config_a)
    hash_b = config_hash(config_b)
    runs_a = store.list_runs_for_config_hash(hash_a)
    runs_b = store.list_runs_for_config_hash(hash_b)

    run_label_map_a = {format_run_option(run): run["id"] for run in runs_a} if runs_a else {"latest": None}
    run_label_map_b = {format_run_option(run): run["id"] for run in runs_b} if runs_b else {"latest": None}
    run_cols = st.columns(2)
    run_label_a = run_cols[0].selectbox("Run A", list(run_label_map_a.keys()), key="compare_run_a")
    run_label_b = run_cols[1].selectbox("Run B", list(run_label_map_b.keys()), key="compare_run_b")

    if st.button("비교 실행", use_container_width=False):
        comparison = compare_presets(
            path_a,
            path_b,
            store_path=DEFAULT_DB_PATH,
            run_a_id=run_label_map_a[run_label_a],
            run_b_id=run_label_map_b[run_label_b],
        )
        st.session_state["last_comparison"] = comparison

    comparison = st.session_state.get("last_comparison")
    if not comparison:
        st.caption("Config A/B를 선택하고 비교를 실행하세요.")
        return

    if comparison.get("raw_corpus_differs"):
        st.warning("raw corpus differs: fetch signature가 달라서 snapshot 기준 비교를 보여줍니다.")
    else:
        st.success("same raw corpus: 같은 fetch signature 기준으로 재랭킹 비교입니다.")

    st.markdown("**Config Diff**")
    st.json(comparison.get("config_diff", {}))

    results = comparison.get("results")
    if not results:
        st.info("비교할 run 데이터가 부족합니다. 각 config로 Fetch를 한 번 이상 실행하세요.")
        return

    metric_cols = st.columns(3)
    metric_cols[0].metric("Top overlap", results.get("top_overlap", 0))
    metric_cols[1].metric("Only in A", len(results.get("only_in_a", [])))
    metric_cols[2].metric("Only in B", len(results.get("only_in_b", [])))

    diff_cols = st.columns(2)
    with diff_cols[0]:
        st.markdown("**Only in A**")
        st.write(results.get("only_in_a", []))
    with diff_cols[1]:
        st.markdown("**Only in B**")
        st.write(results.get("only_in_b", []))

    st.markdown("**Result Diff**")
    st.dataframe(pd.DataFrame(results.get("deltas", [])), use_container_width=True, hide_index=True)


def show_paper_detail(paper: Paper, rank_options: RankOptions) -> None:
    hits = describe_keyword_hits(paper, rank_options)
    detail_cols = st.columns([2, 1])

    with detail_cols[0]:
        st.subheader(paper.title)
        st.markdown(f"- Source: `{paper.source}`")
        st.markdown(f"- Published: `{paper.published_at or '-'}`")
        st.markdown(f"- Categories: `{', '.join(paper.categories) or '-'}`")
        st.markdown(f"- Track: `{paper.primary_track or '-'}`")
        st.markdown(f"- URL: [abs]({paper.url})")
        if paper.pdf_url:
            st.markdown(f"- PDF: [pdf]({paper.pdf_url})")
        if paper.venue:
            st.markdown(f"- Venue: `{paper.venue}`")
        if paper.decision:
            st.markdown(f"- Decision: `{paper.decision}`")
        if paper.citations is not None:
            st.markdown(f"- Citations: `{paper.citations}`")
        if paper.review_signal is not None:
            st.markdown(f"- Review signal: `{paper.review_signal:.2f}`")
        priority_matches = (paper.source_metadata.get("openalex") or {}).get("matched_priority_entities") or []
        if priority_matches:
            st.markdown("**OpenAlex priority matches**")
            for match in priority_matches:
                st.markdown(
                    "- "
                    + " / ".join(
                        part
                        for part in (
                            str(match.get("catalog_name") or "").strip(),
                            str(match.get("entity_label") or "").strip(),
                            str(match.get("institution_display_name") or "").strip(),
                        )
                        if part
                    )
                )
        st.markdown("**Abstract**")
        st.write(paper.abstract)

    with detail_cols[1]:
        st.markdown("**점수 분해**")
        score_rows = pd.DataFrame(
            [
                {"component": "relevance", "score": paper.relevance_score},
                {"component": "novelty", "score": paper.novelty_score},
                {"component": "empirical", "score": paper.empirical_score},
                {"component": "source_signal", "score": paper.source_signal_score},
                {"component": "momentum", "score": paper.momentum_score},
                {"component": "recency", "score": paper.recency_score},
                {"component": "actionability", "score": paper.actionability_score},
                {"component": "final", "score": paper.final_score},
            ]
        )
        st.dataframe(score_rows, use_container_width=True, hide_index=True)
        st.markdown("**Keyword / track hits**")
        st.write(hits)


def parse_track_definitions_text(value: str) -> dict[str, Any]:
    text = value.strip()
    if not text or runtime_yaml is None:
        return {}
    try:
        loaded = runtime_yaml.safe_load(text) or {}
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def serialize_track_definitions(digest_options: DigestOptions) -> str:
    custom_defs: dict[str, Any] = {}
    builtin_defs = build_digest_options_from_config({"digest": {"tracks": digest_options.tracks}}).track_definitions
    for track_id, definition in digest_options.track_definitions.items():
        if track_id == TRACK_UNASSIGNED:
            continue
        if builtin_defs.get(track_id) == definition:
            continue
        custom_defs[track_id] = {
            "label": definition.get("label", track_id),
            "keywords": list(definition.get("keywords", [])),
        }
    if not custom_defs:
        return ""
    if runtime_yaml is None:
        return json.dumps(custom_defs, ensure_ascii=False, indent=2)
    return runtime_yaml.safe_dump(custom_defs, allow_unicode=True, sort_keys=False)


def serialize_config(config: Mapping[str, Any]) -> str:
    if runtime_yaml is None:
        return json.dumps(dict(config), ensure_ascii=False, indent=2)
    return runtime_yaml.safe_dump(dict(config), allow_unicode=True, sort_keys=False)


def format_fetch_time(value: str | None) -> str:
    if not value:
        return "-"
    try:
        timestamp = dt.datetime.fromisoformat(value)
    except ValueError:
        return value
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def reformat_preset_name(name: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z_-]+", "_", name.strip()).strip("_")
    return sanitized or "preset"


def format_run_option(run: Mapping[str, Any]) -> str:
    finished = run.get("finished_at") or run.get("started_at") or "-"
    return f"#{run['id']} / {run.get('status', '-')} / {finished}"


if __name__ == "__main__":
    main()
