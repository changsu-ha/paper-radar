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
    DEFAULT_DB_PATH,
    DigestOptions,
    FetchOptions,
    Paper,
    PaperRadarStore,
    RankOptions,
    WEIGHT_KEYS,
    assign_tracks,
    build_config_from_options,
    build_digest_options_from_config,
    build_fetch_options_from_config,
    build_rank_options_from_config,
    build_track_digest,
    collect_openreview,
    compare_presets,
    config_hash,
    diff_configs,
    enrich_openalex,
    enrich_papers,
    execute_pipeline,
    fetch_options_signature,
    get_config_path,
    load_config,
    normalize_weight_map,
    paper_from_dict,
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
        self.digest_options = DigestOptions(
            daily_top_k=4,
            weekly_top_k_per_track=2,
            tracks=["manipulation", "world_model", "supporting_ml"],
            track_definitions={
                "manipulation": {"label": "Manipulation", "keywords": ["manipulation", "grasp", "dexterous"]},
                "world_model": {"label": "World Model", "keywords": ["world model", "planning"]},
                "supporting_ml": {"label": "Supporting ML", "keywords": ["dataset", "benchmark"]},
                "unassigned": {"label": "Unassigned", "keywords": []},
            },
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

    def test_preset_roundtrip_preserves_shape_and_strips_llm(self) -> None:
        base_config = load_config("paper_radar_config_robotics.yaml")
        base_config["llm"] = {"enabled": True}
        fetch_options = FetchOptions(
            queries=["robot learning", "humanoid"],
            categories=["cs.RO", "cs.AI"],
            days_back=14,
            max_results_per_query=25,
            enable_semanticscholar=True,
            enable_openreview=True,
            openreview_venues=["ICLR.cc/2026/Conference"],
            openreview_keywords=["robot learning"],
            enable_openalex=True,
        )
        rank_options = RankOptions(
            include_keywords=parse_keywords_input("robot, humanoid, policy"),
            exclude_keywords=parse_keywords_input("survey, editorial"),
            weights={key: 1 for key in WEIGHT_KEYS},
            buckets={key: float(base_config["ranking"]["buckets"][key]) for key in BUCKET_KEYS},
            daily_top_k=5,
        )
        digest_options = DigestOptions(
            daily_top_k=5,
            weekly_top_k_per_track=2,
            tracks=["manipulation", "world_model"],
            track_definitions={
                "manipulation": {"label": "Manipulation", "keywords": ["manipulation"]},
                "world_model": {"label": "World Model", "keywords": ["world model"]},
                "unassigned": {"label": "Unassigned", "keywords": []},
            },
        )
        built = build_config_from_options(base_config, fetch_options, rank_options, digest_options)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "preset.yaml"
            save_config(path, built)
            loaded = load_config(path)

        self.assertEqual(build_fetch_options_from_config(loaded).queries, fetch_options.queries)
        self.assertEqual(build_fetch_options_from_config(loaded).openreview_venues, fetch_options.openreview_venues)
        self.assertEqual(build_rank_options_from_config(loaded).daily_top_k, 5)
        self.assertNotIn("llm", loaded)
        self.assertEqual(loaded["digest"]["tracks"], ["manipulation", "world_model"])

    def test_openreview_extracts_metadata_and_review_signal(self) -> None:
        now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
        response = Mock(status_code=200)
        response.raise_for_status = Mock()
        response.json = Mock(
            return_value={
                "notes": [
                    {
                        "id": "note-1",
                        "forum": "forum-1",
                        "content": {
                            "title": {"value": "Robot World Models"},
                            "abstract": {"value": "We study world models for robot planning."},
                            "authors": {"value": ["Tester One"]},
                            "keywords": {"value": ["robot learning", "world model"]},
                        },
                        "details": {
                            "directReplies": [
                                {
                                    "invitation": "ICLR.cc/2026/Conference/Paper1/-/Official_Review",
                                    "content": {
                                        "rating": {"value": "8: clear accept"},
                                        "confidence": {"value": "4: high confidence"},
                                    },
                                },
                                {
                                    "invitation": "ICLR.cc/2026/Conference/Paper1/-/Decision",
                                    "content": {"decision": {"value": "Accept (Poster)"}},
                                },
                            ]
                        },
                        "cdate": now_ms,
                    }
                ]
            }
        )

        fetch_options = FetchOptions(
            queries=["robot"],
            categories=["cs.RO"],
            days_back=30,
            max_results_per_query=5,
            enable_semanticscholar=False,
            enable_openreview=True,
            openreview_venues=["ICLR.cc/2026/Conference"],
            openreview_keywords=["robot"],
        )

        with patch("paper_radar_core.requests.get", return_value=response):
            papers, status = collect_openreview(fetch_options, pause_s=0.0)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].decision, "Accept (Poster)")
        self.assertEqual(papers[0].review_count, 1)
        self.assertGreater(papers[0].review_signal or 0.0, 0.0)
        self.assertEqual(status["venues"]["ICLR.cc/2026/Conference"]["matched"], 1)

    def test_openalex_fallback_enrichment_prefers_arxiv_id_then_title(self) -> None:
        paper = make_paper(
            title="Robot World Models",
            abstract="We study world models for robot planning.",
            external_id="2604.00001v1",
        )
        fetch_options = FetchOptions(
            queries=["robot"],
            categories=["cs.RO"],
            days_back=7,
            max_results_per_query=5,
            enable_semanticscholar=False,
            enable_openalex=True,
        )

        empty_response = Mock(status_code=200)
        empty_response.raise_for_status = Mock()
        empty_response.json = Mock(return_value={"results": []})

        hit_response = Mock(status_code=200)
        hit_response.raise_for_status = Mock()
        hit_response.json = Mock(
            return_value={
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "cited_by_count": 19,
                        "doi": "https://doi.org/10.1000/openalex",
                        "primary_location": {"source": {"display_name": "OpenReview"}},
                        "primary_topic": {"display_name": "Robot Learning"},
                        "concepts": [{"display_name": "World Models"}],
                        "open_access": {"is_oa": True, "oa_url": "https://example.com/openalex.pdf"},
                    }
                ]
            }
        )

        with patch("paper_radar_core.requests.get", side_effect=[empty_response, hit_response]):
            with patch("paper_radar_core.time.sleep", return_value=None):
                enriched, status = enrich_openalex([paper], fetch_options, env={}, sleep_s=0.0)

        self.assertEqual(status["enriched"], 1)
        self.assertEqual(enriched[0].citations, 19)
        self.assertEqual(enriched[0].venue, "OpenReview")
        self.assertEqual(enriched[0].doi, "10.1000/openalex")
        self.assertIn("World Models", enriched[0].topics)

    def test_build_digest_options_accepts_list_style_track_definitions(self) -> None:
        config = {
            "digest": {
                "daily_top_k": 5,
                "weekly_top_k_per_track": 2,
                "tracks": ["data_selection"],
                "track_definitions": {
                    "data_selection": ["data curation", "data filtering", "data selection"],
                },
            }
        }

        digest_options = build_digest_options_from_config(config)

        self.assertEqual(digest_options.tracks, ["data_selection"])
        self.assertEqual(digest_options.track_definitions["data_selection"]["label"], "Data Selection")
        self.assertEqual(
            digest_options.track_definitions["data_selection"]["keywords"],
            ["data curation", "data filtering", "data selection"],
        )

    def test_assign_tracks_and_digest_support_multilabel(self) -> None:
        paper = make_paper(
            title="Dexterous world model manipulation",
            abstract="We use a world model for dexterous manipulation planning with a new dataset.",
        )
        assigned = assign_tracks([paper], self.digest_options)
        digest = build_track_digest(assigned, self.digest_options)

        self.assertEqual(assigned[0].primary_track, "manipulation")
        self.assertIn("world_model", assigned[0].track_ids)
        self.assertIn("Manipulation", digest.daily_markdown)
        self.assertIn("Weekly Track Digest", digest.weekly_markdown)

    def test_compare_presets_reuses_same_fetch_corpus_and_flags_different_fetch(self) -> None:
        base_config = load_config("paper_radar_config_robotics.yaml")
        config_a = build_config_from_options(
            base_config,
            FetchOptions(
                queries=["robot learning"],
                categories=["cs.RO"],
                days_back=7,
                max_results_per_query=5,
                enable_semanticscholar=False,
            ),
            self.default_rank_options,
        )
        config_b = build_config_from_options(
            base_config,
            FetchOptions(
                queries=["robot learning"],
                categories=["cs.RO"],
                days_back=7,
                max_results_per_query=5,
                enable_semanticscholar=False,
            ),
            RankOptions(
                include_keywords=["robot", "world model"],
                exclude_keywords=[],
                weights={
                    "relevance": 0.4,
                    "novelty": 0.2,
                    "empirical": 0.1,
                    "source_signal": 0.1,
                    "momentum": 0.1,
                    "recency": 0.1,
                    "actionability": 0.0,
                },
                buckets=self.default_rank_options.buckets,
                daily_top_k=8,
            ),
        )
        config_c = build_config_from_options(
            base_config,
            FetchOptions(
                queries=["humanoid"],
                categories=["cs.RO"],
                days_back=14,
                max_results_per_query=5,
                enable_semanticscholar=False,
            ),
            self.default_rank_options,
        )

        papers = rank_papers(
            assign_tracks([make_paper("Robot policy learning", "Real robot policy study.")], self.digest_options),
            self.default_rank_options,
        )
        other_papers = rank_papers(
            assign_tracks([make_paper("Humanoid control", "Humanoid locomotion paper.", external_id="test-9")], self.digest_options),
            self.default_rank_options,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            db_path = tmpdir_path / "paper_radar.sqlite3"
            path_a = tmpdir_path / "config_a.yaml"
            path_b = tmpdir_path / "config_b.yaml"
            path_c = tmpdir_path / "config_c.yaml"
            save_config(path_a, config_a)
            save_config(path_b, config_b)
            save_config(path_c, config_c)

            store = PaperRadarStore(db_path)
            run_a = store.start_run(
                config_hash_value=config_hash(config_a),
                config_path=str(path_a),
                config=config_a,
                fetch_signature=fetch_options_signature(build_fetch_options_from_config(config_a)),
            )
            store.persist_ranked_run(run_a, papers)
            store.finalize_run(run_a, status="completed", total_papers=len(papers), source_status={"ok": True})

            run_c = store.start_run(
                config_hash_value=config_hash(config_c),
                config_path=str(path_c),
                config=config_c,
                fetch_signature=fetch_options_signature(build_fetch_options_from_config(config_c)),
            )
            store.persist_ranked_run(run_c, other_papers)
            store.finalize_run(run_c, status="completed", total_papers=len(other_papers), source_status={"ok": True})

            same_fetch = compare_presets(path_a, path_b, store_path=db_path)
            different_fetch = compare_presets(path_a, path_c, store_path=db_path)

        self.assertFalse(same_fetch["raw_corpus_differs"])
        self.assertIsNotNone(same_fetch["results"])
        self.assertTrue(different_fetch["raw_corpus_differs"])

    def test_execute_pipeline_ignores_old_llm_config_and_persists_outputs(self) -> None:
        config = load_config("paper_radar_config_robotics.yaml")
        config["llm"] = {"enabled": True, "model_summary": "legacy"}
        config["sources"]["semanticscholar"]["enabled"] = False
        config["sources"]["openreview"]["enabled"] = False
        config["sources"]["openalex"]["enabled"] = False

        now = dt.datetime.now(dt.timezone.utc)
        arxiv_response = Mock(status_code=200, text=build_arxiv_feed([now - dt.timedelta(days=1)]))
        arxiv_response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            db_path = tmpdir_path / DEFAULT_DB_PATH.name
            out_dir = tmpdir_path / "data"
            with patch("paper_radar_core.requests.get", return_value=arxiv_response):
                with patch("paper_radar_core.time.sleep", return_value=None):
                    execution = execute_pipeline(
                        config,
                        config_path="paper_radar_config_robotics.yaml",
                        store_path=db_path,
                        out_dir=out_dir,
                        persist=True,
                        export=True,
                        pause_s=0.0,
                        sleep_s=0.0,
                    )

            self.assertIsNotNone(execution.run_id)
            self.assertTrue((out_dir / "daily_radar.md").exists())
            self.assertTrue((out_dir / "weekly_track_digest.md").exists())
            self.assertTrue((out_dir / "papers.jsonl").exists())
            store = PaperRadarStore(db_path)
            self.assertEqual(len(store.load_run_papers(execution.run_id)), 1)

    def test_diff_configs_ignores_llm_only_changes(self) -> None:
        config_a = load_config("paper_radar_config_robotics.yaml")
        config_b = load_config("paper_radar_config_robotics.yaml")
        config_a["llm"] = {"enabled": False}
        config_b["llm"] = {"enabled": True, "model_summary": "legacy"}

        diff = diff_configs(config_a, config_b)

        self.assertNotIn("llm", diff)
        self.assertEqual(diff["weights"], {})
        self.assertEqual(diff["buckets"], {})

    def test_old_snapshot_extra_keys_do_not_break_loader(self) -> None:
        payload = asdict_like(make_paper("Robot paper", "Abstract"))
        payload["summary_ko"] = "legacy summary"
        payload["summary_status"] = "complete"
        payload["evaluator_status"] = "pass"
        payload["evaluator_notes"] = {"legacy": True}

        paper = paper_from_dict(payload)

        self.assertEqual(paper.title, "Robot paper")
        self.assertFalse(hasattr(paper, "summary_ko"))

    def test_rerank_does_not_hit_network(self) -> None:
        paper = make_paper(
            title="Robot policy learning",
            abstract="We propose a robot policy with ablation and real robot results.",
            citations=10,
        )
        with patch("paper_radar_core.requests.get") as mock_get:
            rank_papers(assign_tracks([paper], self.digest_options), self.default_rank_options)
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

    def test_get_config_path_accepts_flag_positional_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "custom.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            self.assertEqual(get_config_path(["--config-path", str(config_path)]), config_path)
            self.assertEqual(get_config_path([str(config_path)]), config_path)

            with patch.dict("os.environ", {"PAPER_RADAR_CONFIG": str(config_path)}, clear=False):
                self.assertEqual(get_config_path([]), config_path)


def make_paper(
    title: str,
    abstract: str,
    citations: int | None = None,
    *,
    external_id: str = "test-1",
) -> Paper:
    now = dt.datetime.now(dt.timezone.utc)
    return Paper(
        source="arxiv",
        external_id=external_id,
        title=title,
        abstract=abstract,
        authors=["Tester"],
        published_at=now.isoformat().replace("+00:00", "Z"),
        updated_at=now.isoformat().replace("+00:00", "Z"),
        url=f"https://example.com/abs/{external_id}",
        pdf_url=f"https://example.com/pdf/{external_id}",
        categories=["cs.RO"],
        citations=citations,
        normalized_title=title.lower(),
        source_metadata={"arxiv": {"external_id": external_id}},
    )


def asdict_like(paper: Paper) -> dict[str, object]:
    return {
        "source": paper.source,
        "external_id": paper.external_id,
        "title": paper.title,
        "abstract": paper.abstract,
        "authors": list(paper.authors),
        "published_at": paper.published_at,
        "updated_at": paper.updated_at,
        "url": paper.url,
        "pdf_url": paper.pdf_url,
        "venue": paper.venue,
        "categories": list(paper.categories),
        "doi": paper.doi,
        "citations": paper.citations,
        "topics": list(paper.topics),
        "decision": paper.decision,
        "review_signal": paper.review_signal,
        "review_count": paper.review_count,
        "canonical_id": paper.canonical_id,
        "track_ids": list(paper.track_ids),
        "primary_track": paper.primary_track,
        "track_reasons": dict(paper.track_reasons),
        "source_metadata": dict(paper.source_metadata),
        "raw": dict(paper.raw),
        "normalized_title": paper.normalized_title,
        "relevance_score": paper.relevance_score,
        "novelty_score": paper.novelty_score,
        "empirical_score": paper.empirical_score,
        "source_signal_score": paper.source_signal_score,
        "momentum_score": paper.momentum_score,
        "recency_score": paper.recency_score,
        "actionability_score": paper.actionability_score,
        "final_score": paper.final_score,
        "bucket": paper.bucket,
    }


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
