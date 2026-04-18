from __future__ import annotations

from pathlib import Path
from typing import Sequence

from paper_radar_core import (
    build_fetch_options_from_config,
    build_rank_options_from_config,
    enrich_papers,
    export_results,
    fetch_papers,
    get_config_path,
    load_config,
    rank_papers,
)


def main(argv: Sequence[str] | None = None) -> None:
    config_path = get_config_path(list(argv) if argv is not None else None)
    config = load_config(config_path)
    fetch_options = build_fetch_options_from_config(config)
    rank_options = build_rank_options_from_config(config)

    papers = fetch_papers(fetch_options)
    enriched = enrich_papers(papers, fetch_options)
    ranked = rank_papers(enriched, rank_options)
    export_results(ranked, Path("data"), top_k=rank_options.daily_top_k)
    print(f"Wrote {len(ranked)} papers to data using config {config_path}")


if __name__ == "__main__":
    main()
