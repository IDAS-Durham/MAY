import pytest
import pandas as pd
import os
import tempfile
from may.population import PopulationManager, Person
from may.geography import Geography, GeographicalUnit

@pytest.fixture
def mock_geography():
    geography = Geography()
    geography.levels = ['SGU']
    sgu = GeographicalUnit(id=1, name='E00000001', level='SGU')
    geography.units = {'E00000001': sgu}
    geography.units_by_level = {'SGU': {'E00000001': sgu}}
    return geography

def test_load_explicit_from_csv(mock_geography):
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, 'pop.csv')
        df = pd.DataFrame({
            'ID': [1, 2],
            'Age': [25, 30],
            'Gender': ['M', 'F'],
            'Area': ['E00000001', 'E00000001'],
            'Extra': ['A', 'B']
        })
        df.to_csv(csv_path, index=False)
        
        pop_manager = PopulationManager(geography=mock_geography, data_dir=tmpdir)
        pop_manager.load_explicit_from_csv(
            filename='pop.csv',
            column_mapping={
                'age': 'Age',
                'sex': 'Gender',
                'geo_unit': 'Area'
            }
        )
        
        assert len(pop_manager.people) == 2
        p1 = pop_manager.people[0]
        assert p1.age == 25
        assert p1.sex == 'male'
        assert p1.geographical_unit.name == 'E00000001'
        assert p1.properties['Extra'] == 'A'
        assert p1.properties['ID'] == 1
        
        p2 = pop_manager.people[1]
        assert p2.age == 30
        assert p2.sex == 'female'
        assert p2.properties['Extra'] == 'B'

def test_load_explicit_missing_file(mock_geography, caplog):
    pop_manager = PopulationManager(geography=mock_geography, data_dir='/tmp')
    pop_manager.load_explicit_from_csv('nonexistent.csv', {})
    assert "not found" in caplog.text
