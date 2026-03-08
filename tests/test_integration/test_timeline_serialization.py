import pytest
import os
import yaml
import h5py
from unittest.mock import patch, MagicMock
import numpy as np

# We focus on the isolated block of logic found in run_world (Lines 335-350)
def execute_serialization_block(world_mock, config, args, logger_mock):
    """
    Simulates the exact serialization block from create_world.py
    for targeted evaluation without running the full 5-minute pipeline.
    """
    serial_config = config.get("serialization", {})
    if serial_config.get("enabled", True):
        logger_mock.info("")
        logger_mock.info("Exporting world to HDF5...")
        output_dir = serial_config.get("output_dir", ".")
        filename = serial_config.get("filename", args.filename)
        
        if output_dir != ".":
            os.makedirs(output_dir, exist_ok=True)
            
        export_path = os.path.join(output_dir, filename)
        config_file = serial_config.get("config_file")
        
        if config_file:
            world_mock.export_to_hdf5(export_path, config_file=config_file)
        else:
            world_mock.export_to_hdf5(export_path)


class TestCreateWorldSerializationRouting:
    """Verifies the engine parses combinations of YAML and CLI arguments natively."""

    @pytest.fixture
    def args_mock(self):
        args = MagicMock()
        args.filename = "default_cli_world.h5"
        return args

    @pytest.fixture
    def world_mock(self):
        return MagicMock()

    @pytest.fixture
    def logger_mock(self):
        return MagicMock()

    def test_serialization_explicitly_disabled(self, world_mock, args_mock, logger_mock):
        """Verify config['serialization']['enabled'] = False aborts export."""
        config = {"serialization": {"enabled": False}}
        
        execute_serialization_block(world_mock, config, args_mock, logger_mock)
        
        # Verify export was never called
        world_mock.export_to_hdf5.assert_not_called()

    def test_serialization_default_fallbacks(self, world_mock, args_mock, logger_mock):
        """Verify empty configs trigger the 'default_cli_world.h5' gracefully without custom args."""
        config = {} # Missing or empty serialization block
        
        execute_serialization_block(world_mock, config, args_mock, logger_mock)
        
        # Verify it defaulted to enabled=True, output_dir=".", used args.filename, and didn't pass custom config
        expected_path = os.path.join(".", args_mock.filename)
        world_mock.export_to_hdf5.assert_called_once_with(expected_path)

    @patch('os.makedirs')
    def test_serialization_custom_output_directory_generation(self, mock_makedirs, world_mock, args_mock, logger_mock):
        """Verify output_dir invokes os.makedirs and forms the correct joined path."""
        custom_dir = "custom_outputs"
        config = {
            "serialization": {
                "enabled": True,
                "output_dir": custom_dir
            }
        }
        
        execute_serialization_block(world_mock, config, args_mock, logger_mock)
        
        mock_makedirs.assert_called_once_with(custom_dir, exist_ok=True)
        expected_path = os.path.join(custom_dir, args_mock.filename)
        world_mock.export_to_hdf5.assert_called_once_with(expected_path)

    def test_serialization_custom_filename_priority(self, world_mock, args_mock, logger_mock):
        """Verify YAML filename completely overrides the CLI fallback."""
        custom_name = "specific_world.h5"
        config = {
            "serialization": {
                "enabled": True,
                "filename": custom_name
            }
        }
        
        execute_serialization_block(world_mock, config, args_mock, logger_mock)
        
        expected_path = os.path.join(".", custom_name)
        world_mock.export_to_hdf5.assert_called_once_with(expected_path)

    def test_serialization_custom_config_link(self, world_mock, args_mock, logger_mock):
        """Verify the custom serializer config gets intercepted and passed as a kwarg."""
        custom_serializer = "custom_serializer.yaml"
        config = {
            "serialization": {
                "enabled": True,
                "config_file": custom_serializer
            }
        }
        
        execute_serialization_block(world_mock, config, args_mock, logger_mock)
        
        expected_path = os.path.join(".", args_mock.filename)
        world_mock.export_to_hdf5.assert_called_once_with(expected_path, config_file=custom_serializer)


@pytest.fixture
def minimal_world():
    """Builds a tiny mocked world in-memory to safely serialize."""
    from may.world import World
    from may.geography import VenueManager
    from may.population import PopulationManager
    from may.config_loader import setup_geography
    
    from may.geography import GeographicalUnit
    from may.geography import Venue
    from may.geography import Geography
    
    geo = Geography(data_dir="", levels=["Region", "MGU", "SGU"])
    
    # Manually inject 1 node per layer so we don't need real CSVs
    root = GeographicalUnit(id=1, name="region_1", level="Region")
    geo.add_geo_unit(root)
    
    mgu = GeographicalUnit(id=2, name="mgu_1", level="MGU", parent=root)
    geo.add_geo_unit(mgu)
    
    sgu = GeographicalUnit(id=3, name="sgu_1", level="SGU", parent=mgu)
    geo.add_geo_unit(sgu)
    
    venues = VenueManager(geo, data_dir="")
    # Manually inject 3 venues
    h1 = Venue(name="house_1", venue_type="company", geographical_unit=sgu)
    h1.id = 1
    h2 = Venue(name="house_2", venue_type="company", geographical_unit=sgu)
    h2.id = 2
    s1 = Venue(name="school_1", venue_type="school", geographical_unit=sgu)
    s1.id = 3
    
    venues.add_venue(h1)
    venues.add_venue(h2)
    venues.add_venue(s1)
    
    from may.population import PopulationManager, Person
    
    pop = PopulationManager(geo, data_dir="")
    # Manually inject 10 people
    for i in range(10):
        person = Person(age=20+i, sex="male" if i % 2 == 0 else "female", geographical_unit=sgu)
        pop.add_person(person)
        
    world = World(geography=geo, population=pop, venues=venues)
    return world

class TestWorldHDF5PayloadIntegrity:
    """Verifies the actual binary output of WorldSerializer using the micro-world layout."""

    @pytest.fixture
    def test_export_path(self, tmp_path):
        """Returns a safe temporary path for the HDF5 file."""
        return str(tmp_path / "micro_world_test.h5")

    def test_execute_hdf5_export_and_read_binary(self, minimal_world, test_export_path):
        """Run the actual exporting script on a mocked world component and read the real .h5 response!"""
        
        # 1. Trigger realistic serialization using the internal method natively.
        # We rely on defaults: `config_file="yaml/serialization_config.yaml"`
        stats = minimal_world.export_to_hdf5(test_export_path)

        # Confirm the statistics return trace matches the minimal_world injection size
        assert stats['num_people'] == 10
        assert stats['num_venues'] == 3
        # In the micro world we have 1 Region, 1 SGU, 1 MGU = 3
        assert stats['num_geo_units'] == 3

        # 2. Crack open the written .h5 and check binary integrity!
        assert os.path.exists(test_export_path)
        
        with h5py.File(test_export_path, 'r') as f:
            
            # --- Metadata Assertions ---
            assert f.attrs['num_people'] == 10
            assert f.attrs['num_venues'] == 3
            assert f.attrs['num_geo_units'] == 3
            assert 'serialization_version' in f.attrs
            assert 'june_zero_version' in f.attrs
            
            # --- Geography Integrity ---
            assert 'geography' in f
            assert 'ids' in f['geography']
            assert len(f['geography']['ids']) == 3
            assert 'levels' in f['geography']
            assert 'parent_ids' in f['geography']
            
            # --- Population Integrity ---
            assert 'population' in f
            assert 'ids' in f['population']
            assert len(f['population']['ids']) == 10
            assert 'ages' in f['population']
            assert 'sexes' in f['population']
            assert 'geo_unit_ids' in f['population']
            
            # Verify data alignment logic - Ages should roughly correspond to what we defined
            ages_ds = f['population']['ages'][:]
            assert len(ages_ds) == 10

            # --- Registry Enumerations ---
            assert 'metadata' in f
            assert 'registries' in f['metadata']
            assert 'geo_levels' in f['metadata']['registries']
            
            # We defined 3 geo objects (Region, MGU, SGU) - verify they are in the binary!
            # Registries are written as datasets containing the string keys (per `_write_registries`)
            geo_levels_binary = [x.decode('utf-8') for x in f['metadata']['registries']['geo_levels'][:]]
            assert "Region" in geo_levels_binary
            assert "MGU" in geo_levels_binary
            assert "SGU" in geo_levels_binary
