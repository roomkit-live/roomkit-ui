"""The combo chevron: without it, editable combos read as plain line edits."""

import pathlib

import roomkit_ui.theme as theme_mod
from roomkit_ui.theme import get_stylesheet


def test_stylesheet_embeds_a_chevron_per_theme(monkeypatch, tmp_path):
    monkeypatch.setattr(theme_mod, "data_dir", lambda: tmp_path)

    for theme in ("dark", "light"):
        qss = get_stylesheet(theme)
        assert "QComboBox::down-arrow" in qss
        assert 'image: url("' in qss

    # One cached SVG per distinct arrow color, actually on disk.
    cache = tmp_path / "cache"
    svgs = list(cache.glob("chevron-*.svg"))
    assert len(svgs) == 2
    for svg in svgs:
        assert "<svg" in svg.read_text(encoding="utf-8")


def test_unwritable_cache_degrades_to_hidden_arrow(monkeypatch, tmp_path):
    monkeypatch.setattr(pathlib.Path, "mkdir", _raise_oserror)
    monkeypatch.setattr(theme_mod, "data_dir", lambda: tmp_path)

    qss = get_stylesheet("dark")
    assert "image: none;" in qss
    assert 'url("' not in qss.split("QComboBox::down-arrow")[1].split("}")[0]


def _raise_oserror(*args, **kwargs):
    raise OSError("read-only")
