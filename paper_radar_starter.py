from __future__ import annotations

from pathlib import Path

from paper_radar_core import (
    DEFAULT_CONFIG_PATH,
    build_fetch_options_from_config,
    build_rank_options_from_config,
    enrich_papers,
    export_results,
    fetch_papers,
    load_config,
    rank_papers,
)


def main() -> None:
    config = load_config(DEFAULT_CONFIG_PATH)
    fetch_options = build_fetch_options_from_config(config)
    rank_options = build_rank_options_from_config(config)

    papers = fetch_papers(fetch_options)
    enriched = enrich_papers(papers, fetch_options)
    ranked = rank_papers(enriched, rank_options)
    export_results(ranked, Path("data"), top_k=rank_options.daily_top_k)
    print(f"Wrote {len(ranked)} papers to data")


if __name__ == "__main__":
    main()
