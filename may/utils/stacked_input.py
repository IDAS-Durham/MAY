"""
Load one logical table from one or more CSV files.

Any config key that names a data file may name several; the files are stacked
into a single table under a strict contract: every file must exist, all files
must share one column set (unless a caller opts into zero-filled column
union), and the key column must be unique within and across files. Violations
raise StackedInputError, so a multi-source load either works exactly like the
equivalent single file or fails loudly.
"""

import logging
import os

import pandas as pd

logger = logging.getLogger("stacked_input")

COLUMN_POLICIES = ("strict", "union_zero_fill")


class StackedInputError(Exception):
    pass


def as_path_list(spec, label):
    """
    Normalize a config value that may be a single path or a list of paths.
    """
    if isinstance(spec, str):
        return [spec]
    if isinstance(spec, (list, tuple)):
        if not spec:
            raise StackedInputError(f"{label}: the file list is empty.")
        non_strings = [p for p in spec if not isinstance(p, str)]
        if non_strings:
            raise StackedInputError(
                f"{label}: every entry must be a path string; got {non_strings!r}."
            )
        return list(spec)
    raise StackedInputError(
        f"{label}: expected a path or a list of paths, got "
        f"{type(spec).__name__} ({spec!r})."
    )


def load_stacked_csv(paths, *, label, key_column=None, column_policy="strict",
                     **read_csv_kwargs):
    """
    Read one or more CSVs and concatenate them into a single DataFrame.

    Args:
        paths: List of file paths (already resolved). All must exist.
        label: Human-readable name of the input, used in error messages.
        key_column: Column that must be unique across the stacked table.
            A string names the column; 0 means "first column of the first
            file". None skips the uniqueness check (rows have no natural key).
        column_policy: "strict" means all files must have the same column set.
            "union_zero_fill" means columns are unioned and a column absent from
            a file is zero-filled for that file's rows, with a warning.
        **read_csv_kwargs: Passed through to pandas.read_csv.

    Returns:
        The concatenated DataFrame, columns in first-file order (strict) or
        first-seen order (union), index reset.
    """
    if column_policy not in COLUMN_POLICIES:
        raise StackedInputError(
            f"{label}: unknown column_policy {column_policy!r}; expected one "
            f"of {list(COLUMN_POLICIES)}."
        )

    missing_files = [p for p in paths if not os.path.exists(p)]
    if missing_files:
        raise StackedInputError(f"{label}: file(s) not found: {missing_files}")

    frames = []
    for path in paths:
        df = pd.read_csv(path, **read_csv_kwargs)
        frames.append((path, df))
        logger.info(f"{label}: read {len(df)} rows from {path}")

    reference_path, reference_df = frames[0]
    reference_cols = list(reference_df.columns)

    if key_column == 0:
        key_column = reference_cols[0]

    if column_policy == "strict":
        for path, df in frames[1:]:
            if set(df.columns) != set(reference_cols):
                extra = sorted(set(df.columns) - set(reference_cols))
                absent = sorted(set(reference_cols) - set(df.columns))
                raise StackedInputError(
                    f"{label}: column mismatch between {reference_path} and "
                    f"{path}. Only in {path}: {extra or 'none'}; missing from "
                    f"{path}: {absent or 'none'}."
                )
        stacked_cols = reference_cols
    else:
        # Column union: order is first-seen across files; a column a file
        # lacks becomes zeros for that file's rows.
        stacked_cols = list(reference_cols)
        seen = set(stacked_cols)
        for _, df in frames[1:]:
            for col in df.columns:
                if col not in seen:
                    seen.add(col)
                    stacked_cols.append(col)
        if key_column is not None:
            for path, df in frames:
                if key_column not in df.columns:
                    raise StackedInputError(
                        f"{label}: key column {key_column!r} is missing from "
                        f"{path}; every file must carry the key."
                    )
        for path, df in frames:
            lacking = [c for c in stacked_cols if c not in df.columns]
            if lacking:
                shown = lacking[:15]
                suffix = "" if len(lacking) <= 15 else f" (+{len(lacking) - 15} more)"
                logger.warning(
                    f"{label}: {path} lacks {len(lacking)} column(s) present in "
                    f"other files; zero-filling them for its rows: {shown}{suffix}"
                )

    normalized = []
    for path, df in frames:
        if column_policy == "union_zero_fill":
            df = df.reindex(columns=stacked_cols, fill_value=0)
        else:
            df = df[stacked_cols]
        normalized.append((path, df))

    if key_column is not None:
        _check_key_uniqueness(normalized, key_column, label)

    stacked = pd.concat([df for _, df in normalized], ignore_index=True)
    if len(paths) > 1:
        logger.info(f"{label}: stacked {len(paths)} files into {len(stacked)} rows")
    return stacked


def _check_key_uniqueness(frames, key_column, label):
    """
    Raise if any key value appears twice, naming the files involved.
    Null keys are skipped; they are the caller's row-validity concern.
    """
    first_seen = {}
    for path, df in frames:
        if key_column not in df.columns:
            raise StackedInputError(
                f"{label}: key column {key_column!r} is missing from {path}; "
                f"found columns {list(df.columns)}."
            )
        keys = df[key_column].dropna()
        in_file_dupes = keys[keys.duplicated()].unique()
        if len(in_file_dupes) > 0:
            raise StackedInputError(
                f"{label}: {path} repeats {len(in_file_dupes)} key(s) in column "
                f"{key_column!r}, e.g. {list(in_file_dupes[:5])}."
            )
        clashes = [(k, first_seen[k]) for k in keys if k in first_seen]
        if clashes:
            examples = [
                f"{k!r} (also in {other})" for k, other in clashes[:5]
            ]
            raise StackedInputError(
                f"{label}: {len(clashes)} key(s) in {path} already appear in "
                f"another file: {examples}."
            )
        for k in keys:
            first_seen[k] = path
