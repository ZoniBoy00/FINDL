import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from findl.core.naming import format_series_title, get_folder_structure


def test_series_title_contains_season_episode():
    result = format_series_title({"series": "Test Show", "season": "Kausi 2", "episode": 3, "title": "Jakso 3 - Kausi 2 - Finale"})
    assert result.startswith("TESTSHOW_S02E03_")
    assert "Jakso" not in result


def test_movie_title_has_no_series_suffix():
    assert format_series_title({"title": "A Movie!"}) == "A_Movie"


def test_series_folder_structure():
    assert get_folder_structure({"series": "Test Show", "season": "Season 2"}) == "TESTSHOW\\Season 2"
