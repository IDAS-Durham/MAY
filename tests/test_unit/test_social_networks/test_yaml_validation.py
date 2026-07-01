import pytest

from may.social_networks import (
    SocialNetworkBuilder,
    register_network_type,
    register_pool_type,
)


# Register stub builders so valid-config tests have something to resolve against.
@register_network_type("_stub_net")
def _stub_net(world, config):
    return {}


@register_pool_type("_stub_pool")
def _stub_pool(world, config):
    return []


def _valid_entry(**overrides):
    entry = {
        "name": "test_network",
        "network_type": "_stub_net",
        "pool_type": "_stub_pool",
        "pool": {},
        "mean_count": 4,
        "storage_key": "test_key",
    }
    entry.update(overrides)
    return entry


def _config(*entries):
    return {"networks": list(entries)}


# Valid config — no error raised

def test_valid_config_does_not_raise():
    SocialNetworkBuilder(None, _config(_valid_entry()))


def test_empty_networks_list_does_not_raise():
    SocialNetworkBuilder(None, {"networks": []})


# Unknown network_type

def test_unknown_network_type_raises():
    with pytest.raises(ValueError, match="network_type"):
        SocialNetworkBuilder(None, _config(_valid_entry(network_type="no_such_type")))


def test_unknown_network_type_error_names_the_bad_value():
    with pytest.raises(ValueError, match="no_such_type"):
        SocialNetworkBuilder(None, _config(_valid_entry(network_type="no_such_type")))


# Unknown pool_type

def test_unknown_pool_type_raises():
    with pytest.raises(ValueError, match="pool_type"):
        SocialNetworkBuilder(None, _config(_valid_entry(pool_type="no_such_pool")))


def test_unknown_pool_type_error_names_the_bad_value():
    with pytest.raises(ValueError, match="no_such_pool"):
        SocialNetworkBuilder(None, _config(_valid_entry(pool_type="no_such_pool")))


# Missing required keys

@pytest.mark.parametrize("missing_key", ["network_type", "pool_type", "storage_key", "mean_count"])
def test_missing_required_key_raises(missing_key):
    entry = _valid_entry()
    del entry[missing_key]
    with pytest.raises(ValueError, match=missing_key):
        SocialNetworkBuilder(None, _config(entry))


# Error identifies the offending network by name

def test_error_includes_network_name():
    entry = _valid_entry(name="my_bad_network", network_type="nonexistent")
    with pytest.raises(ValueError, match="my_bad_network"):
        SocialNetworkBuilder(None, _config(entry))


# Second network in list is also validated

def test_second_network_with_bad_type_raises():
    good = _valid_entry(name="good", storage_key="good_key")
    bad = _valid_entry(name="bad", storage_key="bad_key", network_type="nonexistent")
    with pytest.raises(ValueError, match="nonexistent"):
        SocialNetworkBuilder(None, _config(good, bad))
