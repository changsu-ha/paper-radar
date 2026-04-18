from __future__ import annotations

import os
from typing import Sequence

from paper_radar_core import (
    get_config_path,
    run_radar,
)


def main(argv: Sequence[str] | None = None) -> None:
    config_path = get_config_path(list(argv) if argv is not None else None)
    execution = run_radar(config_path, env=os.environ, persist=True, export=True)
    print(
        f"Wrote {len(execution.ranked_papers)} papers to data using config {config_path} "
        f"(run_id={execution.run_id})"
    )


if __name__ == "__main__":
    main()
