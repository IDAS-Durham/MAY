import pytest
from may.geography.venue import Venue


@pytest.fixture(autouse=True)
def reset_venue_id_counter():
    Venue.reset_id_counter()
