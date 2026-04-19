from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paper_radar_app import (
    discover_config_yaml_paths,
    discover_priority_catalog_paths,
    initialize_session,
    reset_session_state_for_config,
    run_openalex_self_check_from_session,
)


class PaperRadarAppHelperTests(unittest.TestCase):
    def test_discover_config_yaml_paths_includes_configs_and_excludes_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "configs"
            preset_dir = root / "data" / "gui_presets"
            config_dir.mkdir(parents=True)
            preset_dir.mkdir(parents=True)

            base_config = config_dir / "robotics.yaml"
            alt_config = config_dir / "fundamental_ml.yaml"
            catalog = config_dir / "major_universities.yaml"
            prompts = config_dir / "paper_radar_prompts.example.yaml"
            other_yaml = root / "notes.yaml"
            preset = preset_dir / "robot.yaml"

            base_config.write_text("project:\n  name: demo\n", encoding="utf-8")
            alt_config.write_text("project:\n  name: demo\n", encoding="utf-8")
            prompts.write_text("project:\n  name: demo\n", encoding="utf-8")
            other_yaml.write_text("project:\n  name: demo\n", encoding="utf-8")
            preset.write_text("project:\n  name: demo\n", encoding="utf-8")
            catalog.write_text(
                "kind: openalex_affiliation_catalog\ncatalog_name: Major Universities\nentities:\n  stanford:\n    label: Stanford University\n    aliases:\n      - Stanford\n",
                encoding="utf-8",
            )

            discovered = discover_config_yaml_paths(repo_root=root, config_dir=config_dir, preset_dir=preset_dir)
            discovered_paths = set(discovered.values())

            self.assertIn(base_config.resolve(), discovered_paths)
            self.assertIn(alt_config.resolve(), discovered_paths)
            self.assertIn(preset.resolve(), discovered_paths)
            self.assertNotIn(catalog.resolve(), discovered_paths)
            self.assertNotIn(prompts.resolve(), discovered_paths)
            self.assertNotIn(other_yaml.resolve(), discovered_paths)

    def test_discover_priority_catalog_paths_includes_only_catalogs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "configs"
            config_dir.mkdir(parents=True)
            (config_dir / "robotics.yaml").write_text("project:\n  name: demo\n", encoding="utf-8")
            catalog = config_dir / "major_research_labs.yaml"
            catalog.write_text(
                "kind: openalex_affiliation_catalog\ncatalog_name: Major Labs\nentities:\n  openai:\n    label: OpenAI\n    aliases:\n      - OpenAI\n",
                encoding="utf-8",
            )

            discovered = discover_priority_catalog_paths(repo_root=root, config_dir=config_dir)

        self.assertEqual(list(discovered.values()), [catalog.resolve()])

    def test_reset_session_state_for_config_clears_only_runtime_keys(self) -> None:
        state = {
            "config_source_path": "/tmp/config.yaml",
            "config_template": {"project": {"name": "demo"}},
            "fetched_raw_papers": [1, 2, 3],
            "last_fetch_signature": "abc",
            "last_fetch_at": "2026-01-01T00:00:00",
            "last_fetch_count": 3,
            "last_run_id": 7,
            "last_source_status": {"ok": True},
            "selected_paper_label": "1. Paper",
            "last_comparison": {"diff": True},
            "compare_config_a": "a",
            "compare_config_b": "b",
            "compare_run_a": "#1",
            "compare_run_b": "#2",
            "openalex_self_check_result": {"http_ok": True},
            "preset_name": "legacy",
            "weight_relevance": 0.25,
        }

        reset_session_state_for_config(state)

        self.assertEqual(state["config_source_path"], "/tmp/config.yaml")
        self.assertEqual(state["config_template"], {"project": {"name": "demo"}})
        self.assertEqual(state["fetched_raw_papers"], [])
        self.assertIsNone(state["last_fetch_signature"])
        self.assertIsNone(state["last_fetch_at"])
        self.assertEqual(state["last_fetch_count"], 0)
        self.assertIsNone(state["last_run_id"])
        self.assertEqual(state["last_source_status"], {})
        self.assertEqual(state["selected_paper_label"], "")
        self.assertIsNone(state["last_comparison"])
        self.assertIsNone(state["openalex_self_check_result"])
        self.assertEqual(state["preset_name"], "")
        self.assertEqual(state["weight_relevance"], 0.25)

    def test_initialize_session_keeps_selected_yaml_on_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            selected = root / "selected.yaml"
            startup = root / "startup.yaml"
            for path in (selected, startup):
                path.write_text("project:\n  name: demo\n", encoding="utf-8")

            state = {
                "initialized": True,
                "config_source_path": str(selected.resolve()),
            }
            dummy_streamlit = SimpleNamespace(session_state=state)

            with patch("paper_radar_app.st", dummy_streamlit), patch(
                "paper_radar_app.load_config",
                side_effect=AssertionError("initialize_session should not reload the startup config"),
            ), patch("paper_radar_app.apply_config_to_session") as apply_config:
                initialize_session(startup)

            self.assertEqual(state["config_source_path"], str(selected.resolve()))
            apply_config.assert_not_called()

    def test_run_openalex_self_check_from_session_uses_current_config_env_and_enabled(self) -> None:
        state = {
            "config_template": {"sources": {"openalex": {"api_key_env": "CUSTOM_OPENALEX_ENV"}}},
            "queries_text": "test query",
            "categories": ["cs.LG"],
            "days_back": 7,
            "max_results_per_query": 10,
            "enable_semanticscholar": False,
            "enable_openreview": False,
            "openreview_venues_text": "",
            "openreview_keywords_text": "",
            "enable_openalex": True,
        }
        dummy_streamlit = SimpleNamespace(session_state=state)

        with patch("paper_radar_app.st", dummy_streamlit), patch(
            "paper_radar_app.openalex_self_check",
            return_value={"env_present": True, "http_ok": True, "message": "ok"},
        ) as self_check:
            result = run_openalex_self_check_from_session(env={"CUSTOM_OPENALEX_ENV": "secret"})

        self.assertTrue(result["enabled"])
        self.assertEqual(result["api_key_env"], "CUSTOM_OPENALEX_ENV")
        self_check.assert_called_once_with("CUSTOM_OPENALEX_ENV", env={"CUSTOM_OPENALEX_ENV": "secret"})


if __name__ == "__main__":
    unittest.main()

