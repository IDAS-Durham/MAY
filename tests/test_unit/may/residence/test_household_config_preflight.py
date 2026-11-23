import pytest

from may.residence.household_distributor import HouseholdDistributor
from may.utils import path_resolver

CATEGORIES = (
    "categories:\n"
    "  - {name: Kids, symbol: K, attribute: age, type: numerical,"
    " numerical: {min: 0, max: 17}}\n"
    "  - {name: Adults, symbol: A, attribute: age, type: numerical,"
    " numerical: {min: 18, max: null}}\n"
)
RULES = "enabled: true\n"


@pytest.fixture(autouse=True)
def reset_resolver(monkeypatch):
    monkeypatch.setattr(path_resolver, "_resolver", None)


@pytest.fixture
def working_dir(tmp_path, monkeypatch):
    working = tmp_path / "working"
    working.mkdir()
    (working / "data").mkdir()
    monkeypatch.chdir(working)
    return working


@pytest.fixture
def write_block(working_dir):
    """Write household YAML files in the working dir; return the block pointing at them."""

    def write(config_text=CATEGORIES, rules_text=RULES, **overrides):
        (working_dir / "households.yaml").write_text(config_text)
        block = {
            "data_dir": "data",
            "data_file": "households.csv",
            "config_file": "households.yaml",
        }
        if rules_text is not None:
            (working_dir / "rules.yaml").write_text(rules_text)
            block["rules_file"] = "rules.yaml"
        block.update(overrides)
        return block

    return write


def problem_lines(report):
    return [(finding.key, finding.message) for finding in report.problems]


def warning_lines(report):
    return [(finding.key, finding.message) for finding in report.warnings]


def test_clean_block_is_parsed(write_block):
    household_config, report = HouseholdDistributor.parse_config(write_block())
    assert not report.problems and not report.warnings
    assert household_config.data_dir == "data"
    assert household_config.config_path == "households.yaml"
    assert [category["symbol"] for category in household_config.config["categories"]] == [
        "K",
        "A",
    ]
    assert household_config.rules_path == "rules.yaml"
    assert household_config.data_file == "households.csv"
    assert household_config.column_policy == "strict"


def test_column_policy_is_carried(write_block):
    household_config, _ = HouseholdDistributor.parse_config(
        write_block(column_policy="union_zero_fill")
    )
    assert household_config.column_policy == "union_zero_fill"


def test_data_file_list_is_carried_unchecked(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(data_file=["a.csv", "b.csv"])
    )
    assert not report.problems
    assert household_config.data_file == ["a.csv", "b.csv"]


@pytest.mark.parametrize("key", ["data_dir", "config_file", "data_file"])
@pytest.mark.parametrize("blank", [None, ""])
def test_required_key_unset_is_problem(write_block, key, blank):
    block = write_block()
    if blank is None:
        del block[key]
    else:
        block[key] = blank
    household_config, report = HouseholdDistributor.parse_config(block)
    assert household_config is None
    assert problem_lines(report) == [(key, "not set; there is no default")]


def test_every_required_key_unset_is_one_problem_each(working_dir):
    household_config, report = HouseholdDistributor.parse_config({})
    assert household_config is None
    assert [key for key, _ in problem_lines(report)] == [
        "data_dir",
        "config_file",
        "data_file",
    ]


def test_config_file_found_under_data_dir(write_block, working_dir):
    block = write_block()
    (working_dir / "households.yaml").rename(working_dir / "data" / "households.yaml")
    household_config, report = HouseholdDistributor.parse_config(block)
    assert not report.problems
    assert household_config.config_path == "data/households.yaml"


def test_config_file_not_found_is_problem(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_file="missing.yaml")
    )
    assert household_config is None
    assert problem_lines(report) == [
        ("config_file", "not found; tried missing.yaml, data/missing.yaml")
    ]


def test_config_file_invalid_yaml_is_problem(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_text="categories:\n  - [unclosed\n")
    )
    assert household_config is None
    assert problem_lines(report) == [
        ("config_file", "households.yaml is not valid YAML at line 3, column 1")
    ]


def test_config_file_empty_is_problem(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_text="# nothing\n")
    )
    assert household_config is None
    assert problem_lines(report) == [("config_file", "households.yaml is empty")]


def test_config_file_not_mapping_is_problem(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_text="- Kids\n")
    )
    assert household_config is None
    assert problem_lines(report) == [
        ("config_file (households.yaml)", "must be a mapping; got sequence (list)")
    ]


def test_categories_unset_is_problem(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_text="demotion: {}\n")
    )
    assert household_config is None
    assert problem_lines(report) == [
        ("config_file (households.yaml): categories", "not set")
    ]


def test_categories_not_list_is_problem(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_text="categories:\n  Kids: K\n")
    )
    assert household_config is None
    assert problem_lines(report) == [
        ("config_file (households.yaml): categories", "must be a list; got mapping (dict)")
    ]


def test_category_not_mapping_is_problem(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_text="categories:\n  - Kids\n")
    )
    assert household_config is None
    assert problem_lines(report) == [
        (
            "config_file (households.yaml): categories[0]",
            "must be a mapping; got scalar (str)",
        )
    ]


@pytest.mark.parametrize("key", ["name", "symbol", "attribute", "type"])
def test_category_key_unset_is_problem(write_block, key):
    fields = {"name": "Kids", "symbol": "K", "attribute": "age", "type": "categorical"}
    del fields[key]
    entry = ", ".join(f"{field}: {value}" for field, value in fields.items())
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_text=f"categories:\n  - {{{entry}}}\n")
    )
    assert household_config is None
    assert problem_lines(report) == [
        (f"config_file (households.yaml): categories[0].{key}", "not set")
    ]


def test_category_type_unknown_is_problem(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(
            config_text="categories:\n  - {name: Kids, symbol: K, attribute: age, type: range}\n"
        )
    )
    assert household_config is None
    assert problem_lines(report) == [
        (
            "config_file (households.yaml): categories[0].type",
            "must be 'numerical' or 'categorical'; got 'range'",
        )
    ]


def test_every_bad_category_is_reported(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(
            config_text=(
                "categories:\n"
                "  - {symbol: K, attribute: age, type: numerical}\n"
                "  - {name: A, symbol: A, attribute: age, type: range}\n"
            )
        )
    )
    assert household_config is None
    assert [key for key, _ in problem_lines(report)] == [
        "config_file (households.yaml): categories[0].name",
        "config_file (households.yaml): categories[1].type",
    ]


def test_demotion_priority_unknown_category_is_warning(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(
            config_text=CATEGORIES + "demotion:\n  priority:\n    Kids: 1\n    Kidz: 2\n"
        )
    )
    assert not report.problems
    assert household_config is not None
    assert warning_lines(report) == [
        (
            "config_file (households.yaml): demotion.priority.Kidz",
            "not a category; ignored. Categories: ['Kids', 'Adults']",
        )
    ]


def test_blank_demotion_and_priority_are_clean(write_block):
    for demotion in ("demotion:\n", "demotion:\n  priority:\n"):
        _, report = HouseholdDistributor.parse_config(
            write_block(config_text=CATEGORIES + demotion)
        )
        assert not report.problems and not report.warnings


@pytest.mark.parametrize(
    "demotion, key",
    [
        ("demotion: [Kids]\n", "demotion"),
        ("demotion:\n  priority: [Kids]\n", "demotion.priority"),
    ],
)
def test_demotion_not_mapping_is_problem(write_block, demotion, key):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_text=CATEGORIES + demotion)
    )
    assert household_config is None
    assert problem_lines(report) == [
        (f"config_file (households.yaml): {key}", "must be a mapping; got sequence (list)")
    ]


def test_rules_file_unset_is_warning(write_block):
    household_config, report = HouseholdDistributor.parse_config(write_block(rules_text=None))
    assert not report.problems
    assert household_config.rules_path is None
    assert warning_lines(report) == [
        ("rules_file", "not set; relationship rules disabled")
    ]


def test_rules_file_found_under_data_dir(write_block, working_dir):
    block = write_block()
    (working_dir / "rules.yaml").rename(working_dir / "data" / "rules.yaml")
    household_config, report = HouseholdDistributor.parse_config(block)
    assert not report.problems
    assert household_config.rules_path == "data/rules.yaml"


def test_rules_file_not_found_is_problem(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(rules_file="missing.yaml")
    )
    assert household_config is None
    assert problem_lines(report) == [
        ("rules_file", "not found; tried missing.yaml, data/missing.yaml")
    ]


def test_rules_file_empty_is_warning_and_disables_rules(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(rules_text="# nothing\n")
    )
    assert not report.problems
    assert household_config.rules_path is None
    assert warning_lines(report) == [
        ("rules_file", "rules.yaml is empty; relationship rules disabled")
    ]


def test_rules_file_not_mapping_is_problem(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(rules_text="- enabled\n")
    )
    assert household_config is None
    assert problem_lines(report) == [
        ("rules_file (rules.yaml)", "must be a mapping; got sequence (list)")
    ]


def test_rules_file_invalid_yaml_is_problem(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(rules_text="enabled: [unclosed\n")
    )
    assert household_config is None
    assert problem_lines(report) == [
        ("rules_file", "rules.yaml is not valid YAML at line 2, column 1")
    ]


def test_config_and_rules_problems_reported_together(write_block):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_file="missing.yaml", rules_file="gone.yaml")
    )
    assert household_config is None
    assert [key for key, _ in problem_lines(report)] == ["config_file", "rules_file"]


def test_preflight_returns_parse_report(write_block):
    report = HouseholdDistributor.preflight(write_block(rules_text=None))
    assert not report.problems
    assert warning_lines(report) == [
        ("rules_file", "not set; relationship rules disabled")
    ]


@pytest.mark.parametrize("value", ["high", "true", "[1]"])
def test_demotion_priority_not_number_is_problem(write_block, value):
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_text=CATEGORIES + f"demotion:\n  priority:\n    Kids: {value}\n")
    )
    assert household_config is None
    assert [key for key, _ in problem_lines(report)] == [
        "config_file (households.yaml): demotion.priority.Kids"
    ]
    assert problem_lines(report)[0][1].startswith("must be a number; got ")


@pytest.mark.parametrize("category_type", ["numerical", "categorical"])
@pytest.mark.parametrize("sub_block", ["", " [0, 17]"], ids=["blank", "list"])
def test_category_type_block_not_mapping_is_problem(write_block, category_type, sub_block):
    config_text = (
        "categories:\n"
        f"  - name: Kids\n    symbol: K\n    attribute: age\n    type: {category_type}\n"
        f"    {category_type}:{sub_block}\n"
    )
    household_config, report = HouseholdDistributor.parse_config(
        write_block(config_text=config_text)
    )
    assert household_config is None
    assert [key for key, _ in problem_lines(report)] == [
        f"config_file (households.yaml): categories[0].{category_type}"
    ]


@pytest.mark.parametrize("key", ["config_file", "rules_file"])
def test_directory_as_file_is_problem(write_block, working_dir, key):
    (working_dir / "folder.yaml").mkdir()
    household_config, report = HouseholdDistributor.parse_config(
        write_block(**{key: "folder.yaml"})
    )
    assert household_config is None
    assert [problem_key for problem_key, _ in problem_lines(report)] == [key]
    assert problem_lines(report)[0][1].startswith("folder.yaml could not be read: ")


def test_non_utf8_file_is_problem(write_block, working_dir):
    block = write_block()
    (working_dir / "households.yaml").write_bytes(b"categories: \xff\xfe\n")
    household_config, report = HouseholdDistributor.parse_config(block)
    assert household_config is None
    assert problem_lines(report) == [
        ("config_file", "households.yaml could not be read: not UTF-8 text")
    ]
