from __future__ import annotations

import copy
import datetime as dt
import json
import os
from dataclasses import asdict
from pathlib import Path
from zoneinfo import ZoneInfo

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

from paper_radar_core import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_PRESET_DIR,
    DEFAULT_TIMEZONE,
    BUCKET_KEYS,
    WEIGHT_KEYS,
    FetchOptions,
    RankOptions,
    build_config_from_options,
    build_fetch_options_from_config,
    build_rank_options_from_config,
    describe_keyword_hits,
    enrich_papers,
    export_results,
    fetch_options_signature,
    fetch_papers,
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
    st.caption("검색 설정을 바꾸고, 수집 결과를 바로 재정렬하면서 볼 수 있는 로컬 실험용 UI입니다.")

    initialize_session(config_path)
    preset_paths = get_preset_paths(config_path)

    with st.sidebar:
        st.header("프리셋")
        preset_labels = list(preset_paths.keys())
        st.selectbox("불러올 preset", preset_labels, key="preset_selector")
        preset_cols = st.columns(2)
        if preset_cols[0].button("Preset 불러오기", use_container_width=True):
            load_preset_into_session(preset_paths[st.session_state["preset_selector"]])
            st.rerun()

        st.text_input("저장 이름", key="preset_name")
        if preset_cols[1].button("Save Preset", use_container_width=True):
            preset_name = st.session_state["preset_name"].strip()
            if not preset_name:
                st.error("저장할 preset 이름을 입력하세요.")
            else:
                save_current_preset(preset_name)
                st.success(f"`{preset_name}` preset을 저장했습니다.")

        st.divider()
        st.header("Fetch 설정")
        st.number_input("검색 기간 (일)", min_value=1, max_value=365, key="days_back")
        st.number_input("query별 최대 결과", min_value=1, max_value=500, key="max_results_per_query")
        st.text_area("검색 query", height=180, key="queries_text")
        all_categories = sorted(set(CATEGORY_OPTIONS + st.session_state.get("categories", [])))
        st.multiselect("카테고리", all_categories, key="categories")
        st.toggle("Semantic Scholar enrich 사용", key="enable_semanticscholar")

        st.divider()
        st.header("Ranking 설정")
        st.text_area("include_keywords", height=140, key="include_keywords_text")
        st.text_area("exclude_keywords", height=100, key="exclude_keywords_text")
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
        st.number_input("daily_top_k", min_value=1, max_value=100, key="daily_top_k")

    fetch_options = build_fetch_options_from_session()
    rank_options = build_rank_options_from_session()
    current_config = build_config_from_options(
        st.session_state["config_template"],
        fetch_options,
        rank_options,
    )
    current_fetch_signature = fetch_options_signature(fetch_options)
    needs_refetch = (
        bool(st.session_state["fetched_raw_papers"])
        and st.session_state.get("last_fetch_signature") != current_fetch_signature
    )

    show_top_controls(rank_options, needs_refetch)

    if st.button("Fetch", type="primary", use_container_width=False):
        try:
            with st.spinner("arXiv 수집과 metadata enrich를 실행 중입니다..."):
                fetched = fetch_papers(fetch_options)
                enriched = enrich_papers(fetched, fetch_options, env=os.environ)
        except Exception as exc:
            st.error(f"Fetch 실행 중 오류가 발생했습니다: {exc}")
        else:
            st.session_state["fetched_raw_papers"] = [asdict(paper) for paper in enriched]
            st.session_state["last_fetch_signature"] = current_fetch_signature
            st.session_state["last_fetch_at"] = dt.datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).isoformat()
            st.session_state["last_fetch_count"] = len(enriched)
            needs_refetch = False
            if not enriched:
                st.warning("수집된 논문이 없습니다. query, 기간, 네트워크 상태를 확인하세요.")

    ranked_papers = rank_current_session_papers(rank_options)
    show_metrics(ranked_papers)

    action_cols = st.columns(2)
    if action_cols[0].button("Export 현재 결과", use_container_width=True):
        export_results(ranked_papers, Path("data"), top_k=rank_options.daily_top_k)
        st.success("`data/daily_radar.md`, `data/papers.jsonl`로 export했습니다.")
    action_cols[1].download_button(
        label="현재 config 다운로드",
        data=serialize_config(current_config),
        file_name="paper_radar_gui_config.yaml",
        mime="text/yaml",
        use_container_width=True,
    )

    if not ranked_papers:
        st.info("아직 fetch 결과가 없습니다. 왼쪽 설정을 조정한 뒤 `Fetch`를 눌러 주세요.")
        return

    records = papers_to_records(ranked_papers)
    dataframe = pd.DataFrame(records)
    st.subheader("결과 테이블")
    st.dataframe(dataframe, use_container_width=True, hide_index=True)

    options = [f"{idx + 1}. {paper.title}" for idx, paper in enumerate(ranked_papers)]
    if st.session_state.get("selected_paper_label") not in options:
        st.session_state["selected_paper_label"] = options[0]
    st.selectbox("상세 보기", options, key="selected_paper_label")
    selected_idx = options.index(st.session_state["selected_paper_label"])
    show_paper_detail(ranked_papers[selected_idx], rank_options)


def get_runtime_config_path() -> Path:
    return get_config_path()


def initialize_session(config_path: Path) -> None:
    resolved_config_path = config_path.expanduser()
    if (
        st.session_state.get("initialized")
        and st.session_state.get("config_source_path") == str(resolved_config_path)
    ):
        return

    config = load_config(resolved_config_path)
    apply_config_to_session(config)
    st.session_state["config_template"] = copy.deepcopy(config)
    st.session_state["fetched_raw_papers"] = []
    st.session_state["last_fetch_signature"] = None
    st.session_state["last_fetch_at"] = None
    st.session_state["last_fetch_count"] = 0
    st.session_state["preset_selector"] = "기본 예제"
    st.session_state["config_source_path"] = str(resolved_config_path)
    st.session_state["preset_selector"] = get_default_preset_label(resolved_config_path)
    st.session_state["preset_name"] = ""
    st.session_state["selected_paper_label"] = ""
    st.session_state["initialized"] = True


def get_preset_paths() -> dict[str, Path]:
    preset_paths = {"기본 예제": DEFAULT_CONFIG_PATH}
    if DEFAULT_PRESET_DIR.exists():
        for path in sorted(DEFAULT_PRESET_DIR.glob("*.yaml")):
            preset_paths[path.stem] = path
    return preset_paths


def get_default_preset_label(config_path: Path) -> str:
    if config_path == DEFAULT_CONFIG_PATH:
        return "기본 예제"
    return f"실행 config ({config_path.name})"


def get_preset_paths(config_path: Path) -> dict[str, Path]:
    preset_paths = {get_default_preset_label(config_path): config_path}
    if config_path != DEFAULT_CONFIG_PATH:
        preset_paths["기본 예제"] = DEFAULT_CONFIG_PATH
    if DEFAULT_PRESET_DIR.exists():
        for path in sorted(DEFAULT_PRESET_DIR.glob("*.yaml")):
            preset_paths[path.stem] = path
    return preset_paths


def load_preset_into_session(path: Path) -> None:
    config = load_config(path)
    apply_config_to_session(config)
    st.session_state["config_template"] = copy.deepcopy(config)


def apply_config_to_session(config: dict[str, object]) -> None:
    fetch_options = build_fetch_options_from_config(config)
    rank_options = build_rank_options_from_config(config)
    normalized_weights, _, _ = normalize_weight_map(rank_options.weights)

    st.session_state["days_back"] = int(fetch_options.days_back)
    st.session_state["max_results_per_query"] = int(fetch_options.max_results_per_query)
    st.session_state["queries_text"] = "\n".join(fetch_options.queries)
    st.session_state["categories"] = list(fetch_options.categories)
    st.session_state["enable_semanticscholar"] = bool(fetch_options.enable_semanticscholar)
    st.session_state["include_keywords_text"] = "\n".join(rank_options.include_keywords)
    st.session_state["exclude_keywords_text"] = "\n".join(rank_options.exclude_keywords)
    for weight_key in WEIGHT_KEYS:
        st.session_state[f"weight_{weight_key}"] = float(normalized_weights[weight_key])
    for bucket_key in BUCKET_KEYS:
        st.session_state[f"bucket_{bucket_key}"] = float(rank_options.buckets.get(bucket_key, 0.0))
    st.session_state["daily_top_k"] = int(rank_options.daily_top_k)


def build_fetch_options_from_session() -> FetchOptions:
    template = st.session_state["config_template"]
    api_key_env = (
        template.get("sources", {})
        .get("semanticscholar", {})
        .get("api_key_env", "SEMANTIC_SCHOLAR_API_KEY")
    )
    return FetchOptions(
        queries=split_multiline_list(st.session_state["queries_text"]),
        categories=[str(category).strip() for category in st.session_state["categories"] if str(category).strip()],
        days_back=int(st.session_state["days_back"]),
        max_results_per_query=int(st.session_state["max_results_per_query"]),
        enable_semanticscholar=bool(st.session_state["enable_semanticscholar"]),
        semanticscholar_api_key_env=str(api_key_env),
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


def rank_current_session_papers(rank_options: RankOptions) -> list:
    raw_papers = st.session_state.get("fetched_raw_papers", [])
    if not raw_papers:
        return []
    papers = [paper_from_dict(item) for item in raw_papers]
    return rank_papers(papers, rank_options)


def save_current_preset(name: str) -> None:
    fetch_options = build_fetch_options_from_session()
    rank_options = build_rank_options_from_session()
    config = build_config_from_options(st.session_state["config_template"], fetch_options, rank_options)
    safe_name = reformat_preset_name(name)
    save_config(DEFAULT_PRESET_DIR / f"{safe_name}.yaml", config)


def show_top_controls(rank_options: RankOptions, needs_refetch: bool) -> None:
    normalized_weights, raw_sum, normalized = normalize_weight_map(rank_options.weights)
    weight_line = ", ".join(f"{key}={value:.3f}" for key, value in normalized_weights.items())
    st.caption(f"현재 weight 합계: {raw_sum:.4f}")
    if normalized:
        st.warning(f"weight 합계가 1.0이 아니라서 정규화 적용 중입니다. {weight_line}")
    else:
        st.caption(f"정규화된 weights: {weight_line}")

    if needs_refetch:
        st.warning("Fetch 관련 설정이 바뀌었습니다. 현재 결과는 이전 fetch 기준이며, 새 설정을 반영하려면 `Fetch`를 다시 실행하세요.")
    else:
        st.caption("현재 결과는 현재 fetch 설정과 동기화되어 있습니다.")


def show_metrics(ranked_papers: list) -> None:
    total_count = len(ranked_papers)
    must_read_count = sum(1 for paper in ranked_papers if paper.bucket == "must_read")
    top_score = ranked_papers[0].final_score if ranked_papers else 0.0
    last_fetch_at = st.session_state.get("last_fetch_at")
    metric_cols = st.columns(4)
    metric_cols[0].metric("총 논문 수", total_count)
    metric_cols[1].metric("Must Read", must_read_count)
    metric_cols[2].metric("최고 점수", f"{top_score:.2f}")
    metric_cols[3].metric("최근 Fetch", format_fetch_time(last_fetch_at))


def show_paper_detail(paper, rank_options: RankOptions) -> None:
    hits = describe_keyword_hits(paper, rank_options)
    detail_cols = st.columns([2, 1])

    with detail_cols[0]:
        st.subheader(paper.title)
        st.markdown(f"- Source: `{paper.source}`")
        st.markdown(f"- Published: `{paper.published_at or '-'}`")
        st.markdown(f"- Categories: `{', '.join(paper.categories) or '-'}`")
        st.markdown(f"- URL: [abs]({paper.url})")
        if paper.pdf_url:
            st.markdown(f"- PDF: [pdf]({paper.pdf_url})")
        if paper.venue:
            st.markdown(f"- Venue: `{paper.venue}`")
        if paper.citations is not None:
            st.markdown(f"- Citations: `{paper.citations}`")
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
        st.markdown("**키워드 hit 설명**")
        st.write(
            {
                "include_hits": hits["include_hits"],
                "exclude_hits": hits["exclude_hits"],
                "bucket": paper.bucket,
            }
        )


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


def serialize_config(config: dict[str, object]) -> str:
    try:
        import yaml as runtime_yaml
    except ModuleNotFoundError:
        return json.dumps(config, ensure_ascii=False, indent=2)
    return runtime_yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


if __name__ == "__main__":
    main()
