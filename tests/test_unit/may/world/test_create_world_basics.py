import os
import sys
import numpy as np
import numba as nb
import pytest
from unittest.mock import patch, MagicMock
import create_world
from create_world import set_random_seed, main, setup_population
from may.population import PopulationError
from may.utils import path_resolver as pr

def test_set_random_seed_consistency():
    """
    Test that set_random_seed ensures reproducibility in both 
    numpy and numba random generations.
    """
    # Define a pure numba function to test numba random state
    @nb.njit
    def get_numba_random_float():
        return np.random.random()

    # Seed 1
    seed_value = 42
    set_random_seed(seed_value)
    np_val_1 = np.random.random()
    nb_val_1 = get_numba_random_float()
    
    # Different operations to advance the state
    np.random.random(10)
    
    # Reset Seed 1
    set_random_seed(seed_value)
    np_val_2 = np.random.random()
    nb_val_2 = get_numba_random_float()
    
    # They should be exactly equal
    assert np_val_1 == np_val_2, "Numpy random generation is not deterministic with the same seed"
    assert nb_val_1 == nb_val_2, "Numba random generation is not deterministic with the same seed"
    
    # Seed 2 (should be different)
    set_random_seed(seed_value + 1)
    np_val_3 = np.random.random()
    assert np_val_1 != np_val_3, "Different seeds produced the same random number"

@patch('create_world.setup_geography')
def test_main_cli_arg_parsing(mock_setup_geography):
    """
    Test that main() correctly parses CLI arguments and attempts to open the correct config.
    We test up until the config open logic (lines 60-79).
    """
    # We patch setup_geography but we actually expect it to fail reading
    # if the config does not exist, so let's use a real, minimal file
    test_config_path = "tests/test_data/micro_world/test_micro_config.yaml"
    
    # First, test default arguments (no args passed). We mock sys.argv.
    # We expect a FileNotFoundError because it defaults to configs/2021/config.yaml
    # (see create_world.py argparse default) which may or may not exist in the
    # test env, but let's mock open to be safe.
    with patch('sys.argv', ['create_world.py']):
        with patch('builtins.open', side_effect=FileNotFoundError) as mock_open:
            with pytest.raises(FileNotFoundError):
                main()
            mock_open.assert_called_with(
                "configs/2021/config.yaml", "r", encoding="utf-8-sig"
            )

    # Second, test custom command line arguments.
    with patch('sys.argv', ['create_world.py', '--config', test_config_path, '--filename', 'test_out.h5']):
        # We mock open again just to see if it reaches lines 78-79 successfully
        with patch('builtins.open') as mock_open:
            # We mock yaml reading to return an empty dict
            with patch('yaml.safe_load', return_value={}):
                # It will then throw an error or exit because setup_geography won't work properly
                # with an empty dictionary but we only care that it got here
                mock_setup_geography.return_value = (MagicMock(), None)
                
                # Mock world and venues so it does not crash when moving forward
                with patch('create_world.VenueManager'), patch('create_world.run_preflight'):
                    with patch('create_world.PopulationManager'):
                        with patch('create_world.World'):
                            # Stop it from executing the big timeline logic and return early by patching
                            # we can just let it run through safely since it's mocked
                            try:
                                main()
                            except Exception:
                                pass # We only care that config was read
                                
            # Assert config was attempted to be opened
            mock_open.assert_any_call(test_config_path, "r", encoding="utf-8-sig")


def test_unknown_population_type_rejected():
    """A typo'd population.type must fail loud, not silently run matrix."""
    config = {"population": {"type": "explict"}}
    with pytest.raises(PopulationError, match="Unknown population.type"):
        setup_population(config, MagicMock())


def test_explicit_population_missing_filename_rejected():
    """explicit mode without a filename fails loud through the same mechanism."""
    config = {"population": {"type": "explicit"}}
    with pytest.raises(PopulationError, match="requires a 'filename'"):
        setup_population(config, MagicMock())


def test_batch_data_dir_is_resolved_once_for_every_mode():
    """${data_root} templating applies in explicit_batch mode: data_dir is
    resolved once and the same resolved value reaches both the constructor and
    the batch loader (no divergent raw re-read)."""
    old = pr._resolver
    pr.init(config_root="/cfg", data_root="/data", output_root="/out")
    try:
        config = {"population": {"type": "explicit_batch",
                                 "data_dir": "${data_root}/population"}}
        with patch("create_world.PopulationManager") as MockPM:
            setup_population(config, MagicMock())
        assert MockPM.call_args.kwargs["data_dir"] == "/data/population"
        loader = MockPM.return_value.load_batch_explicit_from_csv
        assert loader.call_args.kwargs["data_dir"] == "/data/population"
    finally:
        pr._resolver = old


class TimelineReached(Exception):
    pass


def test_main_hands_the_world_and_its_config_to_run_timeline(tmp_path):
    """create_world holds no timeline logic: the whole timeline is one call."""
    config_path = tmp_path / "config.yaml"
    (tmp_path / "venues_config.yaml").write_text("venue_types: {}\n", encoding="utf-8")
    config_path.write_text(
        f"venues:\n  data_dir: {tmp_path}\n"
        f"serialization:\n  enabled: false\n  output_dir: {tmp_path}\n"
        "timeline:\n  enabled: true\n  steps:\n"
        "    - type: attribute\n      config: age.yaml\n",
        encoding="utf-8",
    )
    old = pr._resolver
    try:
        with patch("create_world.setup_geography", return_value=(MagicMock(), None)), \
                patch("create_world.VenueManager"), \
                patch("create_world.PopulationManager"), \
                patch("create_world.World") as world_class, \
                patch("create_world.run_timeline", side_effect=TimelineReached) as run_timeline:
            with pytest.raises(TimelineReached):
                main(create_world.parse_args(["--config", str(config_path)]))
    finally:
        pr._resolver = old
        create_world.bp._recorder = None

    world, world_config = run_timeline.call_args.args
    assert world is world_class.return_value
    assert world_config["timeline"]["steps"] == [{"type": "attribute", "config": "age.yaml"}]


def test_main_exits_when_the_timeline_fails(tmp_path):
    """The library raises; only the entry point turns a timeline failure into an exit."""
    config_path = tmp_path / "config.yaml"
    (tmp_path / "venues_config.yaml").write_text("venue_types: {}\n", encoding="utf-8")
    config_path.write_text(
        f"venues:\n  data_dir: {tmp_path}\nserialization:\n  enabled: false\n  output_dir: {tmp_path}\n",
        encoding="utf-8",
    )
    old = pr._resolver
    try:
        with patch("create_world.setup_geography", return_value=(MagicMock(), None)), \
                patch("create_world.VenueManager"), \
                patch("create_world.PopulationManager"), \
                patch("create_world.World"), \
                patch("create_world.run_timeline",
                      side_effect=create_world.TimelineError("step failed")) as run_timeline:
            with pytest.raises(SystemExit) as excinfo:
                main(create_world.parse_args(["--config", str(config_path)]))
    finally:
        pr._resolver = old
        create_world.bp._recorder = None

    assert excinfo.value.code == 1
    run_timeline.assert_called_once()


def write_world_config(tmp_path, venues_yaml="venue_types: {}\n"):
    """Config whose venue YAML lives only under venues.data_dir, with serialisation on."""
    venues_dir = tmp_path / "venues"
    venues_dir.mkdir()
    (venues_dir / "venues.yaml").write_text(venues_yaml, encoding="utf-8")
    (venues_dir / "companies.csv").write_text("geo_unit,industry_code\nA,C\n", encoding="utf-8")
    schema_path = tmp_path / "serialization.yaml"
    schema_path.write_text(
        "venues:\n  types:\n    company:\n      properties: [industry_code]\n", encoding="utf-8"
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"venues:\n  data_dir: {venues_dir}\n  config_file: venues.yaml\n"
        f"serialization:\n  enabled: true\n  config_file: {schema_path}\n"
        f"  output_dir: {tmp_path / 'output'}\n",
        encoding="utf-8",
    )
    return config_path


COMPANY_VENUES = (
    "settings:\n  filter_by_geography: false\n"
    "venue_types:\n  company:\n    filename: companies.csv\n"
)
BROKEN_VENUES = "venue_types:\n  company:\n    enabled: 'yes'\n    filename: companies.csv\n"
WARNING_VENUES = (
    "venue_types:\n  company:\n    filename: companies.csv\n    filter_column: industry_code\n"
)


def run_main(config_path, *extra_args):
    old = pr._resolver
    try:
        return main(create_world.parse_args(["--config", str(config_path), *extra_args]))
    finally:
        pr._resolver = old
        create_world.bp._recorder = None


def test_venue_config_only_under_data_dir_with_serialisation_loads_venues(tmp_path):
    """Regression: the schema-gap check must not reopen the venue YAML relative to the cwd."""
    config_path = write_world_config(tmp_path, COMPANY_VENUES)
    with patch("create_world.setup_geography", return_value=(MagicMock(), None)), \
            patch("create_world.PopulationManager"), \
            patch("create_world.World") as world_class, \
            patch("create_world.run_timeline", side_effect=TimelineReached):
        with pytest.raises(TimelineReached):
            run_main(config_path)
    venues = world_class.call_args.kwargs["venues"]
    assert "company" in venues.get_venue_types()


def test_config_problem_exits_before_geography_loads(tmp_path):
    config_path = write_world_config(tmp_path, BROKEN_VENUES)
    with patch("create_world.setup_geography") as setup_geography:
        with pytest.raises(SystemExit) as excinfo:
            run_main(config_path)
    assert excinfo.value.code == 1
    setup_geography.assert_not_called()


def test_preflight_only_clean_config_stops_before_the_build(tmp_path):
    config_path = write_world_config(tmp_path)
    with patch("create_world.setup_geography") as setup_geography:
        assert run_main(config_path, "--preflight-only") is None
    setup_geography.assert_not_called()
    assert not (tmp_path / "output").exists()


def test_preflight_only_warnings_alone_exit_cleanly(tmp_path):
    config_path = write_world_config(tmp_path, WARNING_VENUES)
    with patch("create_world.setup_geography") as setup_geography:
        assert run_main(config_path, "--preflight-only") is None
    setup_geography.assert_not_called()


def test_preflight_only_problems_exit_with_one(tmp_path):
    config_path = write_world_config(tmp_path, BROKEN_VENUES)
    with pytest.raises(SystemExit) as excinfo:
        run_main(config_path, "--preflight-only")
    assert excinfo.value.code == 1
