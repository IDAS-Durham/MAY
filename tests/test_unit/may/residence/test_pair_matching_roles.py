"""
`pair_matching` with `roles: [X, X]` is rejected at load.

`len(roles) != 2 or not set(roles) <= set(rule.roles)` passed for a repeated role: the
length is 2 and `{X}` is a subset. Allocation then looked for "the other role" with
`next(r for r in roles if r != role_name)` and raised an uncaught StopIteration, after
the world had been built up to that point. The sibling checks in the same block raise a
named ValueError; `len(set(roles))` is the whole test.
"""
import pytest
import yaml

from may.residence.relationship_rules import RelationshipRulesValidator


def _rules_file(tmp_path, roles):
    config = {
        "enabled": True,
        "rules": [{
            "name": "Adult pair",
            "patterns": ["0 0 2 0"],
            "roles": {"role_A": {"categories": ["Adults"], "count": 1},
                      "role_B": {"categories": ["Adults"], "count": 1}},
            "selection_order": ["role_A", "role_B"],
            "constraints": [{
                "type": "pair_matching",
                "roles": roles,
                "categorical_attribute": {
                    "attribute": "sex", "same_category_probability": 0.05,
                },
            }],
        }],
    }
    path = tmp_path / "relationship_rules.yaml"
    path.write_text(yaml.safe_dump(config))
    return str(path)


def test_a_repeated_role_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="exactly 2 different roles"):
        RelationshipRulesValidator(categories=[], config_file=_rules_file(tmp_path, ["role_A", "role_A"]))


def test_two_different_roles_still_load(tmp_path):
    validator = RelationshipRulesValidator(
        categories=[], config_file=_rules_file(tmp_path, ["role_A", "role_B"])
    )

    assert len(validator.rules) == 1


def test_a_role_outside_the_rule_is_still_rejected(tmp_path):
    with pytest.raises(ValueError, match="exactly 2 different roles"):
        RelationshipRulesValidator(categories=[], config_file=_rules_file(tmp_path, ["role_A", "role_Z"]))


def test_three_roles_are_still_rejected(tmp_path):
    with pytest.raises(ValueError, match="exactly 2 different roles"):
        RelationshipRulesValidator(
            categories=[],
            config_file=_rules_file(tmp_path, ["role_A", "role_B", "role_A"]),
        )
