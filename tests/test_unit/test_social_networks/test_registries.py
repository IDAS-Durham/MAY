import pytest

from may.social_networks import (
    network_type_builders,
    register_network_type,
    pool_type_builders,
    register_pool_type,
)


def test_register_network_type():
    @register_network_type("_test_net")
    def my_builder(world, config):
        return {}

    assert "_test_net" in network_type_builders
    assert network_type_builders["_test_net"]({}, {}) == {}


def test_register_pool_type():
    @register_pool_type("_test_pool")
    def my_pool(world, config):
        return []

    assert "_test_pool" in pool_type_builders
    assert pool_type_builders["_test_pool"]({}, {}) == []


def test_register_network_type_preserves_function_name():
    @register_network_type("_test_net_name")
    def named_builder(world, config):
        return {}

    assert network_type_builders["_test_net_name"].__name__ == "named_builder"


def test_register_pool_type_preserves_function_name():
    @register_pool_type("_test_pool_name")
    def named_pool(world, config):
        return []

    assert pool_type_builders["_test_pool_name"].__name__ == "named_pool"
