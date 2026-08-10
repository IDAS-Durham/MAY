"""Holds every shipped read and write to an encoding it names.

Python's ``open()`` in text mode takes the platform's locale encoding, which on
Windows is the ANSI code page, cp1252 for Western and Spanish locales. Reading a
UTF-8 config under cp1252 raises UnicodeDecodeError where the text contains an
uppercase accented vowel such as A-acute, whose UTF-8 bytes cp1252 leaves
undefined, and turns the rest of the accents into mojibake. macOS and Linux use
UTF-8 as their locale encoding, so both outcomes belong to Windows.

The tests cover both halves: the shipped files decode as UTF-8, and the code
opening them names the encoding it wants.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]

# Directories whose Python ships to other machines, so every file it opens
# needs an encoding of its own. One-off data-preparation scripts run on the
# machine that builds the inputs and stay outside this list.
SHIPPED_CODE = ["may", "scripts"]

TEXT_DATA_SUFFIXES = {".yaml", ".yml", ".csv"}

# Calls that open a file in text mode. A call naming an encoding satisfies the
# check, and binary mode carries bytes, so the scan passes over both.
_TEXT_CALL = re.compile(r"(?<![\w.])open\(|\.open\(|\.read_text\(|\.write_text\(")
_BINARY_MODE = re.compile(r"""['"][rwax+]*b[rwax+]*['"]""")


def _iter_shipped_python():
    for name in SHIPPED_CODE:
        yield from sorted((REPO / name).rglob("*.py"))
    yield REPO / "create_world.py"


def _matching_paren(text, open_index):
    """Index of the ``)`` closing the ``(`` at *open_index*, or -1."""
    depth = 0
    quote = None
    i = open_index
    while i < len(text):
        char = text[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def test_shipped_text_files_are_utf8():
    """Every config and data file we ship decodes as strict UTF-8."""
    offenders = []
    for root in ("configs", "data", "tests/test_data"):
        base = REPO / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_DATA_SUFFIXES:
                continue
            try:
                path.read_bytes().decode("utf-8")
            except UnicodeDecodeError as exc:
                offenders.append(f"{path.relative_to(REPO)}: {exc}")
    assert not offenders, "files are not valid UTF-8:\n" + "\n".join(offenders)


def test_shipped_code_names_an_encoding_on_every_text_call():
    """Every shipped text call states the encoding it reads or writes.

    A comment such as ``# BASICA`` written with an accented A is enough to end
    a run on a Windows machine, so the encoding is stated at each call site.
    """
    offenders = []
    for path in _iter_shipped_python():
        source = path.read_bytes().decode("utf-8")
        for match in _TEXT_CALL.finditer(source):
            open_paren = match.end() - 1
            close_paren = _matching_paren(source, open_paren)
            if close_paren < 0:
                continue
            args = source[open_paren + 1:close_paren]
            if "encoding=" in args or _BINARY_MODE.search(args):
                continue
            # urlopen and gzip.open handle their own bytes, so the scan
            # passes over them.
            preceding = source[max(0, match.start() - 8):match.start()]
            if preceding.endswith("url") or preceding.endswith("gzip."):
                continue
            line = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(REPO)}:{line}: {match.group()}...)")
    assert not offenders, (
        "text-mode calls taking the locale encoding, which is cp1252 on "
        "Windows; name an encoding at each one:\n" + "\n".join(offenders)
    )


# Each of these encodes to a byte cp1252 leaves undefined, so reading the file
# under a Windows locale raises. Capital A-acute and I-acute are the two that
# ordinary Spanish text reaches for, and a left arrow is common enough in a
# comment. Lowercase accents and N-tilde decode to mojibake, which the checks
# above cover.
UNDECODABLE_UNDER_CP1252 = ["Á", "Í", "←"]


@pytest.mark.parametrize("character", UNDECODABLE_UNDER_CP1252)
def test_accented_config_loads_when_the_locale_is_cp1252(
    character, tmp_path, monkeypatch
):
    """The loader reads the file under a Windows-style locale default.

    The character sits in a comment, which is enough on its own to decide
    whether the file can be read.
    """
    import builtins

    from may.config_loader import load_config

    config = tmp_path / "config.yaml"
    config.write_text(
        f"# sector {character} comment\n"
        f"population:\n  data_dir: somewhere\n",
        encoding="utf-8",
    )
    with pytest.raises(UnicodeDecodeError):
        config.read_bytes().decode("cp1252")

    real_open = builtins.open

    def cp1252_default_open(file, mode="r", *args, **kwargs):
        if "b" not in mode and "encoding" not in kwargs:
            kwargs["encoding"] = "cp1252"
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", cp1252_default_open)

    assert load_config(str(config)) == {"population": {"data_dir": "somewhere"}}
