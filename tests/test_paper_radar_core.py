from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_radar_core import (
    _warn,
    ArxivClient,
    BUCKET_KEYS,
    WEIGHT_KEYS,
    FetchOptions,
    Paper,
    RankOptions,
    build_config_from_options,
    build_fetch_options_from_config,
    build_rank_options_from_config,
    enrich_papers,
    export_results,
    fetch_papers,
    load_config,
    normalize_weight_map,
    parse_keywords_input,
    rank_papers,
    save_config,
)


class PaperRadarCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.default_rank_options = RankOptions(
            include_keywords=["robot", "manipulation", "policy"],
            exclude_keywords=["survey"],
            weights={
                "relevance": 0.25,
                "novelty": 0.2,
                "empirical": 0.15,
                "source_signal": 0.1,
                "momentum": 0.1,
                "recency": 0.1,
                "actionability": 0.1,
            },
            buckets={
                "must_read": 85.0,
                "worth_reading": 70.0,
                "skim": 55.0,
            },
            daily_top_k=8,
        )

    def test_days_back_filters_results_and_stops_on_old_page(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        fresh_a = now - dt.timedelta(days=1)
        fresh_b = now - dt.timedelta(days=3)
        stale_a = now - dt.timedelta(days=10)
        stale_b = now - dt.timedelta(days=12)

        responses = [
            Mock(status_code=200, text=build_arxiv_feed([fresh_a, fresh_b])),
            Mock(status_code=200, text=build_arxiv_feed([stale_a, stale_b])),
        ]
        for response in responses:
            response.raise_for_status = Mock()

        with patch("paper_radar_core.requests.get", side_effect=responses) as mock_get:
            with patch("paper_radar_core.time.sleep", return_value=None):
                papers = ArxivClient(pause_s=0.0, page_size=2).search(
                    query="robot learning",
                    categories=["cs.RO"],
                    days_back=7,
                    max_results=4,
                )

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(len(papers), 2)
        self.assertTrue(all(paper.published_at and "T" in paper.published_at for paper in papers))

    def test_exclude_keyword_forces_archive(self) -> None:
        paper = make_paper(
            title="A Robot Manipulation Survey",
            abstract="This survey covers robot manipulation and policy learning.",
        )
        ranked = rank_papers([paper], self.default_rank_options)
        self.assertEqual(ranked[0].final_score, 0.0)
        self.assertEqual(ranked[0].bucket, "archive")

    def test_weight_normalization_is_consistent(self) -> None:
        paper = make_paper(
            title="Robot policy learning",
            abstract="We propose a robot policy with ablation and real robot results.",
        )
        normalized_rank_options = RankOptions(
            include_keywords=self.default_rank_options.include_keywords,
            exclude_keywords=self.default_rank_options.exclude_keywords,
            weights={key: value * 2 for key, value in self.default_rank_options.weights.items()},
            buckets=self.default_rank_options.buckets,
            daily_top_k=8,
        )

        baseline = rank_papers([paper], self.default_rank_options)[0]
        doubled = rank_papers([paper], normalized_rank_options)[0]
        normalized_weights, raw_sum, used_normalization = normalize_weight_map(normalized_rank_options.weights)

        self.assertAlmostEqual(baseline.final_score, doubled.final_score, places=2)
        self.assertAlmostEqual(sum(normalized_weights.values()), 1.0, places=6)
        self.assertAlmostEqual(raw_sum, 2.0, places=6)
        self.assertTrue(used_normalization)

    def test_preset_roundtrip_preserves_config_shape(self) -> None:
        base_config = load_config("paper_radar_config.example.yaml")
        fetch_options = FetchOptions(
            queries=["robot learning", "humanoid"],
            categories=["cs.RO", "cs.AI"],
            days_back=14,
            max_results_per_query=25,
            enable_semanticscholar=True,
        )
        rank_options = RankOptions(
            include_keywords=parse_keywords_input("robot, humanoid, policy"),
            exclude_keywords=parse_keywords_input("survey, editorial"),
            weights={key: 1 for key in WEIGHT_KEYS},
            buckets={key: float(base_config["ranking"]["buckets"][key]) for key in BUCKET_KEYS},
            daily_top_k=5,
        )
        built = build_config_from_options(base_config, fetch_options, rank_options)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "preset.yaml"
            save_config(path, built)
            loaded = load_config(path)

        self.assertEqual(build_fetch_options_from_config(loaded).queries, fetch_options.queries)
        self.assertEqual(build_fetch_options_from_config(loaded).days_back, 14)
        self.assertEqual(build_rank_options_from_config(loaded).daily_top_k, 5)
        self.assertAlmostEqual(sum(build_rank_options_from_config(loaded).weights.values()), 1.0, places=6)

    def test_fetch_enrich_rank_export_pipeline_with_mock_http(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        arxiv_response = Mock(status_code=200, text=build_arxiv_feed([now - dt.timedelta(days=1)]))
        arxiv_response.raise_for_status = Mock()
        semantic_response = Mock(status_code=200)
        semantic_response.json = Mock(
            return_value={
                "data": [
                    {
                        "venue": "CoRL",
                        "citationCount": 42,
                        "fieldsOfStudy": ["Robotics"],
                        "externalIds": {"DOI": "10.1000/test"},
                        "openAccessPdf": {"url": "https://example.com/test.pdf"},
                    }
                ]
            }
        )

        def fake_get(url, **kwargs):
            if "arxiv" in url:
                return arxiv_response
            if "semanticscholar" in url:
                return semantic_response
            raise AssertionError(f"Unexpected URL: {url}")

        fetch_options = FetchOptions(
            queries=["robot learning"],
            categories=["cs.RO"],
            days_back=7,
            max_results_per_query=5,
            enable_semanticscholar=True,
        )

        with patch("paper_radar_core.requests.get", side_effect=fake_get):
            with patch("paper_radar_core.time.sleep", return_value=None):
                fetched = fetch_papers(fetch_options, pause_s=0.0)
                enriched = enrich_papers(
                    fetched,
                    fetch_options,
                    env={"SEMANTIC_SCHOLAR_API_KEY": "test-key"},
                    sleep_s=0.0,
                )
                ranked = rank_papers(enriched, self.default_rank_options)

        self.assertEqual(len(fetched), 1)
        self.assertEqual(enriched[0].venue, "CoRL")
        self.assertEqual(enriched[0].citations, 42)
        self.assertEqual(ranked[0].doi, "10.1000/test")

        with tempfile.TemporaryDirectory() as tmpdir:
            export_results(ranked, tmpdir, top_k=3)
            digest_text = Path(tmpdir, "daily_radar.md").read_text(encoding="utf-8")
            jsonl_text = Path(tmpdir, "papers.jsonl").read_text(encoding="utf-8")

        self.assertIn("Daily Paper Radar", digest_text)
        self.assertIn('"citations": 42', jsonl_text)

    def test_rerank_does_not_hit_network(self) -> None:
        paper = make_paper(
            title="Robot policy learning",
            abstract="We propose a robot policy with ablation and real robot results.",
            citations=10,
        )
        with patch("paper_radar_core.requests.get") as mock_get:
            rank_papers([paper], self.default_rank_options)
        mock_get.assert_not_called()

    def test_warn_does_not_raise_when_stderr_is_invalid(self) -> None:
        broken_stream = Mock()
        broken_stream.write.side_effect = OSError(22, "Invalid argument")
        broken_stream.flush.side_effect = OSError(22, "Invalid argument")

        with patch("paper_radar_core.sys.stderr", broken_stream):
            with patch("paper_radar_core.sys.__stderr__", broken_stream):
                _warn("[warn] synthetic failure")

    def test_semantic_scholar_oserror_is_swallowed(self) -> None:
        paper = make_paper(
            title="Robot policy learning",
            abstract="We propose a robot policy with ablation and real robot results.",
        )
        fetch_options = FetchOptions(
            queries=["robot learning"],
            categories=["cs.RO"],
            days_back=7,
            max_results_per_query=5,
            enable_semanticscholar=True,
        )

        with patch("paper_radar_core.requests.get", side_effect=OSError(22, "Invalid argument")):
            with patch("paper_radar_core.time.sleep", return_value=None):
                enriched = enrich_papers(
                    [paper],
                    fetch_options,
                    env={"SEMANTIC_SCHOLAR_API_KEY": "test-key"},
                    sleep_s=0.0,
                )

        self.assertEqual(len(enriched), 1)
        self.assertIsNone(enriched[0].venue)


def make_paper(title: str, abstract: str, citations: int | None = None) -> Paper:
    now = dt.datetime.now(dt.timezone.utc)
    return Paper(
        source="arxiv",
        external_id="test-1",
        title=title,
        abstract=abstract,
        authors=["Tester"],
        published_at=now.isoformat().replace("+00:00", "Z"),
        updated_at=now.isoformat().replace("+00:00", "Z"),
        url="https://example.com/abs/test-1",
        pdf_url="https://example.com/pdf/test-1",
        categories=["cs.RO"],
        citations=citations,
        normalized_title=title.lower(),
    )


def build_arxiv_feed(published_dates: list[dt.datetime]) -> str:
    entries = []
    for idx, published in enumerate(published_dates, start=1):
        published_text = published.isoformat().replace("+00:00", "Z")
        entries.append(
            f"""
            <entry>
              <id>http://arxiv.org/abs/2604.{idx:05d}v1</id>
              <updated>{published_text}</updated>
              <published>{published_text}</published>
              <title>Robot Paper {idx}</title>
              <summary>We propose a robot policy with real robot ablation.</summary>
              <author><name>Tester</name></author>
              <category term="cs.RO" />
              <link href="https://arxiv.org/pdf/2604.{idx:05d}v1" title="pdf" />
            </entry>
            """
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<feed xmlns='http://www.w3.org/2005/Atom' xmlns:arxiv='http://arxiv.org/schemas/atom'>"
        + "".join(entries)
        + "</feed>"
    )


if __name__ == "__main__":
    unittest.main()
