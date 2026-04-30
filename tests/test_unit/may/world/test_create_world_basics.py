import os
import sys
import numpy as np
import numba as nb
import pytest
from unittest.mock import patch, MagicMock
from create_world import set_random_seed, main

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
    # We expect a FileNotFoundError because it defaults to yaml/config.yaml which
    # may or may not exist in the test env, but let's mock open to be safe.
    with patch('sys.argv', ['create_world.py']):
        with patch('builtins.open', side_effect=FileNotFoundError) as mock_open:
            with pytest.raises(FileNotFoundError):
                main()
            mock_open.assert_called_with("yaml/config.yaml", "r")

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
                with patch('create_world.VenueManager'):
                    with patch('create_world.PopulationManager'):
                        with patch('create_world.World'):
                            # Stop it from executing the big timeline logic and return early by patching
                            # we can just let it run through safely since it's mocked
                            try:
                                main()
                            except Exception:
                                pass # We only care that config was read
                                
            # Assert config was attempted to be opened
            mock_open.assert_any_call(test_config_path, "r")
