from __future__ import annotations

import copy
import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

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
    DEFAULT_CONFIG_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_PRESET_DIR,
    DEFAULT_TIMEZONE,
    BUCKET_KEYS,
    TRACK_UNASSIGNED,
    WEIGHT_KEYS,
    DigestOptions,
    FetchOptions,
    LLMOptions,
    Paper,
    PaperRadarStore,
    RankOptions,
    assign_tracks,
    build_config_from_options,
    build_digest_options_from_config,
    build_fetch_options_from_config,
    build_llm_options_from_config,
    build_rank_options_from_config,
    build_track_digest,
    compare_presets,
    config_hash,
    describe_keyword_hits,
    execute_pipeline,
    export_results,
    fetch_options_signature,
    get_config_path,
    load_config,
    normalize_weight_map,
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


def main() -> None:
    config_path = get_runtime_config_path()
    st.set_page_config(page_title="Paper Radar GUI", layout="wide")
    st.title("Paper Radar GUI")
    st.caption(f"Config: `{config_path}`")
    st.caption(f"SQLite: `{DEFAULT_DB_PATH}`")

    initialize_session(config_path)
    preset_paths = get_preset_paths(config_path)
    store = PaperRadarStore(DEFAULT_DB_PATH)

    with st.sidebar:
        render_sidebar(config_path, preset_paths)

    fetch_options = build_fetch_options_from_session()
    rank_options = build_rank_options_from_session()
    llm_options = build_llm_options_from_session(config_path)
    digest_options = build_digest_options_from_session()
    current_config = build_config_from_options(
        st.session_state["config_template"],
        fetch_options,
        rank_options,
        llm_options,
        digest_options,
    )
    current_fetch_signature = fetch_options_signature(fetch_options)
    needs_refetch = (
        bool(st.session_state.get("fetched_raw_papers"))
        and st.session_state.get("last_fetch_signature") != current_fetch_signature
    )

    show_top_controls(rank_options, llm_options, needs_refetch)

    button_cols = st.columns([1, 1, 1, 2])
    if button_cols[0].button("Fetch", type="primary", use_container_width=True):
        run_fetch(current_config, config_path, current_fetch_signature)
        needs_refetch = False
    if button_cols[1].button("Export", use_container_width=True):
        ranked_now = rank_current_session_papers(rank_options, digest_options)
        export_results(
            ranked_now,
            Path("data"),
            top_k=rank_options.daily_top_k,
            digest_options=digest_options,
        )
        st.success("`data/`에 daily/weekly digest와 papers.jsonl을 저장했습니다.")
    button_cols[2].download_button(
        label="현재 config 다운로드",
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
        render_compare_tab(store, preset_paths)


def get_runtime_config_path() -> Path:
    return get_config_path()


def initialize_session(config_path: Path) -> None:
    resolved = config_path.expanduser().resolve()
    if (
        st.session_state.get("initialized")
        and st.session_state.get("config_source_path") == str(resolved)
    ):
        return

    config = load_config(resolved)
    apply_config_to_session(config, resolved)
    st.session_state["config_template"] = copy.deepcopy(config)
    st.session_state["config_source_path"] = str(resolved)
    st.session_state["fetched_raw_papers"] = []
    st.session_state["last_fetch_signature"] = None
    st.session_state["last_fetch_at"] = None
    st.session_state["last_fetch_count"] = 0
    st.session_state["last_run_id"] = None
    st.session_state["last_source_status"] = {}
    st.session_state["selected_paper_label"] = ""
    st.session_state["preset_name"] = ""
    st.session_state["preset_selector"] = get_default_preset_label(resolved)
    st.session_state["initialized"] = True


def render_sidebar(config_path: Path, preset_paths: dict[str, Path]) -> None:
    st.header("Presets")
    preset_labels = list(preset_paths.keys())
    if st.session_state.get("preset_selector") not in preset_labels:
        st.session_state["preset_selector"] = preset_labels[0]
    st.selectbox("불러올 preset", preset_labels, key="preset_selector")
    preset_cols = st.columns(2)
    if preset_cols[0].button("Preset 로드", use_container_width=True):
        load_preset_into_session(preset_paths[st.session_state["preset_selector"]], config_path)
        st.rerun()
    st.text_input("저장할 이름", key="preset_name")
    if preset_cols[1].button("Preset 저장", use_container_width=True):
        preset_name = st.session_state["preset_name"].strip()
        if not preset_name:
            st.error("저장할 preset 이름을 입력하세요.")
        else:
            save_current_preset(preset_name)
            st.success(f"`{preset_name}` preset을 저장했습니다.")

    st.divider()
    st.header("Fetch 설정")
    st.number_input("검색 기간 (days_back)", min_value=1, max_value=365, key="days_back")
    st.number_input("query별 최대 결과 수", min_value=1, max_value=500, key="max_results_per_query")
    st.text_area("arXiv queries", height=140, key="queries_text")
    all_categories = sorted(set(CATEGORY_OPTIONS + st.session_state.get("categories", [])))
    st.multiselect("카테고리", all_categories, key="categories")
    st.toggle("Semantic Scholar enrich", key="enable_semanticscholar")
    st.toggle("OpenReview 수집", key="enable_openreview")
    st.text_area("OpenReview venues", height=100, key="openreview_venues_text")
    st.text_area("OpenReview keywords", height=80, key="openreview_keywords_text")
    st.toggle("OpenAlex enrich", key="enable_openalex")

    st.divider()
    st.header("Ranking 설정")
    st.text_area("include_keywords", height=120, key="include_keywords_text")
    st.text_area("exclude_keywords", height=80, key="exclude_keywords_text")
    for weight_key in WEIGHT_KEYS:
        st.number_input(
            f"weight.{weight_key}",
            min_value=0.0,
            step=0.01,
            format="%.4f",
            key=f"weight_{weight_key}",
        )
    for bucket_key in BUCKET_KEYS:
        st.number_input(
            f"bucket.{bucket_key}",
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            format="%.1f",
            key=f"bucket_{bucket_key}",
        )

    st.divider()
    st.header("LLM 설정")
    st.toggle("OpenAI summary/evaluator", key="llm_enabled")
    st.text_input("summary model", key="llm_model_summary")
    st.text_input("evaluator model", key="llm_model_evaluator")
    st.number_input("summary_top_n", min_value=1, max_value=50, key="llm_summary_top_n")
    st.text_input("prompts_path", key="llm_prompts_path")
    st.text_input("summary_prompt_id", key="llm_summary_prompt_id")
    st.text_input("evaluator_prompt_id", key="llm_evaluator_prompt_id")
    st.number_input("max_concurrency", min_value=1, max_value=16, key="llm_max_concurrency")
    st.number_input("timeout_s", min_value=10, max_value=300, key="llm_timeout_s")

    st.divider()
    st.header("Digest 설정")
    st.number_input("daily_top_k", min_value=1, max_value=100, key="daily_top_k")
    st.number_input(
        "weekly_top_k_per_track",
        min_value=1,
        max_value=50,
        key="weekly_top_k_per_track",
    )
    st.text_area("track order", height=120, key="digest_tracks_text")
    st.text_area(
        "custom track_definitions (YAML)",
        height=160,
        key="track_definitions_text",
        help="예: my_track:\\n  label: My Track\\n  keywords:\\n    - keyword one",
    )


def get_default_preset_label(config_path: Path) -> str:
    if config_path == DEFAULT_CONFIG_PATH.resolve():
        return "기본 예제"
    return f"실행 config ({config_path.name})"


def get_preset_paths(config_path: Path) -> dict[str, Path]:
    resolved = config_path.resolve()
    preset_paths = {get_default_preset_label(resolved): resolved}
    default_config = DEFAULT_CONFIG_PATH.resolve()
    if resolved != default_config and default_config.exists():
        preset_paths["기본 예제"] = default_config
    if DEFAULT_PRESET_DIR.exists():
        for path in sorted(DEFAULT_PRESET_DIR.glob("*.yaml")):
            preset_paths[path.stem] = path.resolve()
    return preset_paths


def load_preset_into_session(path: Path, current_config_path: Path) -> None:
    config = load_config(path)
    apply_config_to_session(config, current_config_path)
    st.session_state["config_template"] = copy.deepcopy(config)


def apply_config_to_session(config: dict[str, Any], config_path: Path) -> None:
    fetch_options = build_fetch_options_from_config(config)
    rank_options = build_rank_options_from_config(config)
    llm_options = build_llm_options_from_config(config, config_path=config_path)
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
    st.session_state["include_keywords_text"] = "\n".join(rank_options.include_keywords)
    st.session_state["exclude_keywords_text"] = "\n".join(rank_options.exclude_keywords)
    for weight_key in WEIGHT_KEYS:
        st.session_state[f"weight_{weight_key}"] = float(normalized_weights[weight_key])
    for bucket_key in BUCKET_KEYS:
        st.session_state[f"bucket_{bucket_key}"] = float(rank_options.buckets.get(bucket_key, 0.0))
    st.session_state["llm_enabled"] = bool(llm_options.enabled)
    st.session_state["llm_model_summary"] = llm_options.model_summary
    st.session_state["llm_model_evaluator"] = llm_options.model_evaluator
    st.session_state["llm_summary_top_n"] = int(llm_options.summary_top_n)
    st.session_state["llm_prompts_path"] = llm_options.prompts_path or "paper_radar_prompts.example.yaml"
    st.session_state["llm_summary_prompt_id"] = llm_options.summary_prompt_id
    st.session_state["llm_evaluator_prompt_id"] = llm_options.evaluator_prompt_id
    st.session_state["llm_max_concurrency"] = int(llm_options.max_concurrency)
    st.session_state["llm_timeout_s"] = int(llm_options.timeout_s)
    st.session_state["daily_top_k"] = int(digest_options.daily_top_k)
    st.session_state["weekly_top_k_per_track"] = int(digest_options.weekly_top_k_per_track)
    st.session_state["digest_tracks_text"] = "\n".join(digest_options.tracks)
    st.session_state["track_definitions_text"] = serialize_track_definitions(digest_options)


def build_fetch_options_from_session() -> FetchOptions:
    template = st.session_state["config_template"]
    semantic_env = (
        template.get("sources", {})
        .get("semanticscholar", {})
        .get("api_key_env", "SEMANTIC_SCHOLAR_API_KEY")
    )
    openalex_env = (
        template.get("sources", {})
        .get("openalex", {})
        .get("api_key_env", "OPENALEX_API_KEY")
    )
    return FetchOptions(
        queries=split_multiline_list(st.session_state["queries_text"]),
        categories=[str(category).strip() for category in st.session_state["categories"] if str(category).strip()],
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
    )


def build_llm_options_from_session(config_path: Path) -> LLMOptions:
    template = st.session_state["config_template"]
    api_key_env = template.get("llm", {}).get("api_key_env", "OPENAI_API_KEY")
    prompts_path = st.session_state["llm_prompts_path"].strip() or "paper_radar_prompts.example.yaml"
    resolved_prompts = Path(prompts_path)
    if not resolved_prompts.is_absolute():
        resolved_prompts = config_path.resolve().parent / resolved_prompts
    return LLMOptions(
        enabled=bool(st.session_state["llm_enabled"]),
        provider="openai",
        model_summary=st.session_state["llm_model_summary"].strip() or "gpt-4o-mini",
        model_evaluator=st.session_state["llm_model_evaluator"].strip() or "gpt-4o-mini",
        summary_top_n=int(st.session_state["llm_summary_top_n"]),
        prompts_path=str(resolved_prompts),
        summary_prompt_id=st.session_state["llm_summary_prompt_id"].strip() or "daily_radar_ko",
        evaluator_prompt_id=st.session_state["llm_evaluator_prompt_id"].strip() or "evaluator_ko",
        max_concurrency=int(st.session_state["llm_max_concurrency"]),
        timeout_s=int(st.session_state["llm_timeout_s"]),
        api_key_env=str(api_key_env),
    )


def build_digest_options_from_session() -> DigestOptions:
    base = build_digest_options_from_config(st.session_state["config_template"])
    tracks = split_multiline_list(st.session_state["digest_tracks_text"])
    definitions = copy.deepcopy(base.track_definitions)
    custom_defs = parse_track_definitions_text(st.session_state["track_definitions_text"])
    for track_id, definition in custom_defs.items():
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


def run_fetch(current_config: dict[str, Any], config_path: Path, current_fetch_signature: str) -> None:
    try:
        with st.spinner("수집, enrich, ranking, summary/evaluator를 실행하는 중입니다..."):
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

    st.session_state["fetched_raw_papers"] = [asdict(paper) for paper in execution.ranked_papers]
    st.session_state["last_fetch_signature"] = current_fetch_signature
    st.session_state["last_fetch_at"] = dt.datetime.now().isoformat()
    st.session_state["last_fetch_count"] = len(execution.ranked_papers)
    st.session_state["last_run_id"] = execution.run_id
    st.session_state["last_source_status"] = execution.source_status
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
    current_config_path = Path(st.session_state["config_source_path"])
    fetch_options = build_fetch_options_from_session()
    rank_options = build_rank_options_from_session()
    llm_options = build_llm_options_from_session(current_config_path)
    digest_options = build_digest_options_from_session()
    config = build_config_from_options(
        st.session_state["config_template"],
        fetch_options,
        rank_options,
        llm_options,
        digest_options,
    )
    safe_name = reformat_preset_name(name)
    save_config(DEFAULT_PRESET_DIR / f"{safe_name}.yaml", config)


def show_top_controls(rank_options: RankOptions, llm_options: LLMOptions, needs_refetch: bool) -> None:
    normalized_weights, raw_sum, normalized = normalize_weight_map(rank_options.weights)
    weight_line = ", ".join(f"{key}={value:.3f}" for key, value in normalized_weights.items())
    st.caption(f"현재 weight 합계: {raw_sum:.4f}")
    if normalized:
        st.warning(f"weight 합계가 1.0이 아니어서 정규화를 적용 중입니다. {weight_line}")
    else:
        st.caption(f"정규화된 weights: {weight_line}")

    if needs_refetch:
        st.warning("Fetch 관련 설정이 바뀌었습니다. 현재 표는 이전 fetch 기준이며, 새 fetch를 실행해야 반영됩니다.")
    else:
        st.caption("현재 fetch 설정과 결과가 일치합니다.")

    if llm_options.enabled:
        st.caption(
            f"LLM summary/evaluator는 fetch 시점에만 갱신됩니다. 현재 모델: {llm_options.model_summary} / {llm_options.model_evaluator}"
        )


def show_metrics(ranked_papers: list[Paper]) -> None:
    total_count = len(ranked_papers)
    must_read_count = sum(1 for paper in ranked_papers if paper.bucket == "must_read")
    top_score = ranked_papers[0].final_score if ranked_papers else 0.0
    last_fetch_at = st.session_state.get("last_fetch_at")
    metric_cols = st.columns(5)
    metric_cols[0].metric("총 논문 수", total_count)
    metric_cols[1].metric("Must Read", must_read_count)
    metric_cols[2].metric("최고 점수", f"{top_score:.2f}")
    metric_cols[3].metric("최근 Fetch", format_fetch_time(last_fetch_at))
    metric_cols[4].metric("마지막 run", st.session_state.get("last_run_id") or "-")


def render_single_run_tab(ranked_papers: list[Paper], rank_options: RankOptions) -> None:
    if not ranked_papers:
        st.info("아직 fetch 결과가 없습니다. 설정을 조정한 뒤 `Fetch`를 실행하세요.")
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
        st.info("먼저 fetch를 실행하면 track digest를 볼 수 있습니다.")
        return

    exclude_failed = st.checkbox("검증 실패 논문 제외", value=True)
    track_digest = build_track_digest(ranked_papers, digest_options, exclude_failed=exclude_failed)

    digest_cols = st.columns(2)
    with digest_cols[0]:
        st.subheader("Daily Digest")
        st.markdown(track_digest.daily_markdown)
    with digest_cols[1]:
        st.subheader("Weekly Track Digest")
        st.markdown(track_digest.weekly_markdown)


def render_compare_tab(store: PaperRadarStore, preset_paths: dict[str, Path]) -> None:
    st.subheader("Preset Compare")
    labels = list(preset_paths.keys())
    if len(labels) < 2:
        st.info("비교하려면 preset이 두 개 이상 필요합니다.")
        return

    compare_cols = st.columns(2)
    default_b = 1 if len(labels) > 1 else 0
    label_a = compare_cols[0].selectbox("Preset A", labels, key="compare_preset_a")
    label_b = compare_cols[1].selectbox("Preset B", labels, index=default_b, key="compare_preset_b")

    path_a = preset_paths[label_a]
    path_b = preset_paths[label_b]
    config_a = load_config(path_a)
    config_b = load_config(path_b)
    hash_a = config_hash(config_a)
    hash_b = config_hash(config_b)
    runs_a = store.list_runs_for_config_hash(hash_a)
    runs_b = store.list_runs_for_config_hash(hash_b)

    run_label_map_a = {format_run_option(run): run["id"] for run in runs_a} if runs_a else {"latest": None}
    run_label_map_b = {format_run_option(run): run["id"] for run in runs_b} if runs_b else {"latest": None}
    run_cols = st.columns(2)
    selected_run_a = run_cols[0].selectbox("Run A", list(run_label_map_a.keys()), key="compare_run_a")
    selected_run_b = run_cols[1].selectbox("Run B", list(run_label_map_b.keys()), key="compare_run_b")

    if st.button("Compare 실행", use_container_width=False):
        comparison = compare_presets(
            path_a,
            path_b,
            store_path=DEFAULT_DB_PATH,
            run_a_id=run_label_map_a[selected_run_a],
            run_b_id=run_label_map_b[selected_run_b],
        )
        st.session_state["last_comparison"] = comparison

    comparison = st.session_state.get("last_comparison")
    if not comparison:
        st.caption("preset A/B를 선택하고 compare를 실행하세요.")
        return

    if comparison.get("raw_corpus_differs"):
        st.warning("raw corpus differs: fetch signature가 달라서 snapshot 기준 비교를 보여줍니다.")
    else:
        st.success("same raw corpus: 동일 fetch signature 기준 재랭킹 비교입니다.")

    st.markdown("**Preset Diff**")
    st.json(comparison.get("config_diff", {}))

    results = comparison.get("results")
    if not results:
        st.info("비교할 run 데이터가 아직 부족합니다. 각 preset으로 fetch를 한 번씩 실행하세요.")
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
        st.markdown("**Abstract**")
        st.write(paper.abstract)
        if paper.summary_ko:
            st.markdown("**Final Summary**")
            st.markdown(paper.summary_ko)
        if paper.evaluator_status:
            st.markdown(f"**Evaluator verdict:** `{paper.evaluator_status}`")
        if paper.evaluator_notes:
            with st.expander("Evaluator notes"):
                st.json(paper.evaluator_notes)

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


def format_fetch_time(value: str | None) -> str:
    if not value:
        return "-"
    try:
        timestamp = dt.datetime.fromisoformat(value)
    except ValueError:
        return value
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def reformat_preset_name(name: str) -> str:
    sanitized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in name.strip())
    sanitized = sanitized.strip("_")
    return sanitized or "preset"


def parse_track_definitions_text(value: str) -> dict[str, Any]:
    text = value.strip()
    if not text:
        return {}
    if runtime_yaml is None:
        return {}
    try:
        loaded = runtime_yaml.safe_load(text) or {}
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def serialize_track_definitions(digest_options: DigestOptions) -> str:
    custom_defs: dict[str, Any] = {}
    for track_id, definition in digest_options.track_definitions.items():
        if track_id == TRACK_UNASSIGNED:
            continue
        builtin = build_digest_options_from_config({"digest": {"tracks": [track_id]}}).track_definitions.get(track_id)
        if builtin == definition:
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


def serialize_config(config: dict[str, Any]) -> str:
    if runtime_yaml is None:
        return json.dumps(config, ensure_ascii=False, indent=2)
    return runtime_yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


def format_run_option(run: dict[str, Any]) -> str:
    finished = run.get("finished_at") or run.get("started_at") or "-"
    return f"#{run['id']} / {run.get('status', '-') } / {finished}"


if __name__ == "__main__":
    main()
