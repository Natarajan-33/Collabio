"""The migration runner reads the version and name from the file name and refuses odd ones."""

from pathlib import Path

import pytest

from scripts.apply_migration import MigrationError, main, parse_filename


def test_parse_filename_splits_version_and_name():
    path = Path("supabase/migrations/20261014120000_m3_deal_loop.sql")

    assert parse_filename(path) == ("20261014120000", "m3_deal_loop")


@pytest.mark.parametrize("name", ["m3_deal_loop.sql", "2026_m3.sql", "20261014120000_m3.txt"])
def test_parse_filename_rejects_other_names(name):
    with pytest.raises(MigrationError):
        parse_filename(Path(name))


def test_main_needs_exactly_one_argument(capsys):
    assert main([]) == 1
    assert "usage" in capsys.readouterr().out
