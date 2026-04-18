from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paper_radar_app import discover_config_yaml_paths, initialize_session, reset_session_state_for_config


class PaperRadarAppHelperTests(unittest.TestCase):
    def test_discover_config_yaml_paths_includes_configs_and_excludes_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            preset_dir = root / "data" / "gui_presets"
            preset_dir.mkdir(parents=True)

            base_config = root / "paper_radar_config.example.yaml"
            alt_config = root / "paper_radar_config_fundamental_ml.yaml"
            prompts = root / "paper_radar_prompts.example.yaml"
            other_yaml = root / "notes.yaml"
            preset = preset_dir / "robot.yaml"

            for path in (base_config, alt_config, prompts, other_yaml, preset):
                path.write_text("project:\n  name: demo\n", encoding="utf-8")

            discovered = discover_config_yaml_paths(repo_root=root, preset_dir=preset_dir)
            discovered_paths = set(discovered.values())

            self.assertIn(base_config.resolve(), discovered_paths)
            self.assertIn(alt_config.resolve(), discovered_paths)
            self.assertIn(preset.resolve(), discovered_paths)
            self.assertNotIn(prompts.resolve(), discovered_paths)
            self.assertNotIn(other_yaml.resolve(), discovered_paths)

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


if __name__ == "__main__":
    unittest.main()
