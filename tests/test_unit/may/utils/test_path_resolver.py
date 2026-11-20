import os

import pytest

from may.utils import path_resolver
from may.utils.path_resolver import ConfigFileNotFoundError, find_config_file


@pytest.fixture(autouse=True)
def reset_resolver(monkeypatch):
    monkeypatch.setattr(path_resolver, "_resolver", None)


@pytest.fixture
def working_dir(tmp_path, monkeypatch):
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)
    return working


@pytest.fixture
def data_dir(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return str(data)


def test_found_in_working_dir_returned_as_written(working_dir, data_dir):
    (working_dir / "venues.yaml").write_text("")
    assert find_config_file("venues.yaml", data_dir) == "venues.yaml"


def test_falls_back_to_data_dir(working_dir, data_dir):
    open(os.path.join(data_dir, "venues.yaml"), "w").close()
    assert find_config_file("venues.yaml", data_dir) == os.path.join(
        data_dir, "venues.yaml"
    )


def test_working_dir_wins_over_data_dir(working_dir, data_dir):
    (working_dir / "venues.yaml").write_text("")
    open(os.path.join(data_dir, "venues.yaml"), "w").close()
    assert find_config_file("venues.yaml", data_dir) == "venues.yaml"


def test_absolute_path_present_returned_as_written(tmp_path, data_dir):
    absolute = tmp_path / "venues.yaml"
    absolute.write_text("")
    assert find_config_file(str(absolute), data_dir) == str(absolute)


def test_absolute_path_absent_tries_only_itself(tmp_path, data_dir):
    absolute = str(tmp_path / "missing.yaml")
    with pytest.raises(ConfigFileNotFoundError) as caught:
        find_config_file(absolute, data_dir)
    assert caught.value.tried == [absolute]


def test_substitutes_roots_in_path_and_data_dir(tmp_path, working_dir, data_dir):
    path_resolver.init(config_root=str(tmp_path), data_root=data_dir, output_root="")
    (tmp_path / "venues.yaml").write_text("")
    assert find_config_file("${config_root}/venues.yaml", None) == str(
        tmp_path / "venues.yaml"
    )
    open(os.path.join(data_dir, "rules.yaml"), "w").close()
    assert find_config_file("rules.yaml", "${data_root}") == os.path.join(
        data_dir, "rules.yaml"
    )


@pytest.mark.parametrize("empty_data_dir", [None, ""])
def test_no_data_dir_tries_working_dir_only(working_dir, empty_data_dir):
    with pytest.raises(ConfigFileNotFoundError) as caught:
        find_config_file("venues.yaml", empty_data_dir)
    assert caught.value.tried == ["venues.yaml"]


def test_miss_raises_with_both_tried_paths(working_dir, data_dir):
    joined = os.path.join(data_dir, "venues.yaml")
    with pytest.raises(ConfigFileNotFoundError) as caught:
        find_config_file("venues.yaml", data_dir)
    error = caught.value
    assert isinstance(error, FileNotFoundError)
    assert error.path == "venues.yaml"
    assert error.tried == ["venues.yaml", joined]
    assert str(error) == f"not found; tried venues.yaml, {joined}"
