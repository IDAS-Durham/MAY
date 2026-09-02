"""
The values a serialized property column accepts.

The HDF5 writer gives each configured property one column of one type, taken
from the first value it finds, and casts every later value to that type. Where
the values share a kind the cast preserves them. Where they span several kinds
the write either raises or stores an altered value, and by then the whole world
has been built.

The rules below name the type the writer chooses and the values that survive
its cast, so a column can be checked as it is assembled.
"""

INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1
FLOAT32_MAX = 3.4028234663852886e38


class PropertyTypeError(Exception):
    """Raised when a property holds values its column type would alter or reject."""


def output_kind(sample):
    """
    The column kind the writer takes from a property's first value.

    bool subclasses int, so the bool test runs first and keeps true/false
    values in a true/false column. Numbers map to int or float by their own
    type, and every other value maps to text, which is where lists and dicts
    arrive once they have been encoded as JSON.
    """
    if isinstance(sample, bool):
        return "bool"
    if isinstance(sample, int):
        return "int"
    if isinstance(sample, float):
        return "float"
    return "str"


def value_problem(kind, value):
    """
    Why *value* would fail or change on its way into a column of *kind*, or
    None where the cast preserves it.

    Two cases produce a message. One is a cast the writer raises on, such as
    text entering an integer column. The other is a cast that alters the value,
    such as a float entering an integer column, or an integer too large for 32
    bits. A widening cast such as an integer entering a float column keeps the
    value intact and returns None.
    """
    if kind == "bool":
        if isinstance(value, bool):
            return None
        return (
            f"{value!r} ({type(value).__name__}) would become "
            f"{bool(value)!r} in a true/false column"
        )

    if kind == "int":
        if isinstance(value, int):
            if INT32_MIN <= value <= INT32_MAX:
                return None
            return f"{value!r} exceeds the range of a 32-bit integer column"
        if isinstance(value, float):
            return f"{value!r} would be truncated to fit an integer column"
        return (
            f"{value!r} ({type(value).__name__}) cannot be stored in an "
            f"integer column"
        )

    if kind == "float":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # NaN compares false against itself, and the writer uses it to
            # fill the gaps in a float column.
            if value != value or abs(value) <= FLOAT32_MAX:
                return None
            return f"{value!r} overflows a 32-bit float column"
        return (
            f"{value!r} ({type(value).__name__}) cannot be stored in a " f"float column"
        )

    if isinstance(value, str):
        return None
    return (
        f"{value!r} ({type(value).__name__}) cannot be stored in a text "
        f"column; only strings and JSON-encodable values can"
    )


def describe_problems(owner, prop_name, kind, problems, total_bad):
    """
    One line naming the property, its column type, the distinct reasons its
    values would fail or change, and how many values are affected.
    """
    count = "" if total_bad == 1 else f" ({total_bad} values affected)"
    return (
        f"{owner} property {prop_name!r}: column is {kind}, but "
        + "; ".join(problems)
        + count
    )
