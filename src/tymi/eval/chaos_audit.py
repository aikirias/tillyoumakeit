"""Bidirectional Fault Manifest audit (Story 3.6).

Validates that a chaos run's ``FaultManifest`` is a faithful record of the corruption
in the output — in **both** directions:

- **listed → present**: every manifest entry materialized in the chaotic ``Dataset``
  (the recorded cell changed / the structural change is in the Schema).
- **present → listed**: every difference between the chaotic output and the faithful
  ``baseline`` (a changed cell, or a Schema difference) is covered by a manifest entry.

Structural faults are audited by *reconstructing* the expected column set from the
listed structural faults and comparing it to the chaotic Schema (a rename is not a
drop+add). Value faults are audited by a null-aware cell diff on same-named columns.
"""

from __future__ import annotations

from tymi.domain.artifacts import Dataset, FaultManifest, ManifestAudit

_STRUCTURAL = frozenset({"missing_field", "extra_field", "renamed_column", "changed_type"})


def audit_manifest(
    baseline: Dataset, chaotic: Dataset, manifest: FaultManifest
) -> ManifestAudit:
    """Check the bidirectional fault contract between ``manifest`` and the output."""
    listed_not_present: list[str] = []
    present_not_listed: list[str] = []

    _audit_structural(baseline, chaotic, manifest, listed_not_present, present_not_listed)
    checked_cells = _audit_cells(
        baseline, chaotic, manifest, listed_not_present, present_not_listed
    )

    structural_count = sum(1 for e in manifest.entries if e.get("fault_type") in _STRUCTURAL)
    return ManifestAudit(
        valid=not listed_not_present and not present_not_listed,
        listed_not_present=tuple(listed_not_present),
        present_not_listed=tuple(present_not_listed),
        checked=checked_cells + structural_count,
    )


def _audit_structural(
    baseline: Dataset,
    chaotic: Dataset,
    manifest: FaultManifest,
    listed_not_present: list[str],
    present_not_listed: list[str],
) -> None:
    base_cols = set(baseline.schema.names())
    chao_cols = set(chaotic.schema.names())
    base_types = {c.name: c.logical_type.value for c in baseline.schema.columns}
    chao_types = {c.name: c.logical_type.value for c in chaotic.schema.columns}

    listed_missing: set[str] = set()
    listed_extra: set[str] = set()
    listed_renames: dict[str, str] = {}
    listed_changed: dict[str, str] = {}
    for e in manifest.entries:
        ft = e.get("fault_type")
        if ft == "missing_field":
            listed_missing.add(e.get("column"))
        elif ft == "extra_field":
            listed_extra.add(e.get("column"))
        elif ft == "renamed_column":
            listed_renames[e.get("column")] = e.get("new_name")
        elif ft == "changed_type":
            listed_changed[e.get("column")] = e.get("to")

    # forward: every listed structural fault must have materialised in the Schema.
    for col in listed_missing:
        if col in chao_cols:
            listed_not_present.append(f"missing_field {col!r} but the column is still present")
    for col in listed_extra:
        if col not in chao_cols:
            listed_not_present.append(f"extra_field {col!r} but the column is absent from output")
    for old, new in listed_renames.items():
        if old in chao_cols or new not in chao_cols:
            listed_not_present.append(f"renamed_column {old!r}->{new!r} not reflected in output")
    for col, to in listed_changed.items():
        if chao_types.get(col) != to:
            listed_not_present.append(f"changed_type {col!r} to {to} not reflected in output")

    # backward: every real Schema change must be listed.
    rename_old, rename_new = set(listed_renames), set(listed_renames.values())
    for col in sorted(base_cols - chao_cols):  # dropped / renamed-away
        if col not in listed_missing and col not in rename_old:
            present_not_listed.append(f"column {col!r} removed from the schema but not listed")
    for col in sorted(chao_cols - base_cols):  # added / rename target
        if col not in listed_extra and col not in rename_new:
            present_not_listed.append(f"column {col!r} added to the schema but not listed")
    for col in sorted(base_cols & chao_cols):  # type changed in place
        if base_types.get(col) != chao_types.get(col) and col not in listed_changed:
            present_not_listed.append(
                f"column {col!r} type changed "
                f"{base_types.get(col)}->{chao_types.get(col)} but not listed"
            )


def _audit_cells(
    baseline: Dataset,
    chaotic: Dataset,
    manifest: FaultManifest,
    listed_not_present: list[str],
    present_not_listed: list[str],
) -> int:
    if len(baseline.frame) != len(chaotic.frame):
        # a row-count change leaves a region unaudited — the min() below would hide it.
        present_not_listed.append(
            f"row count changed {len(baseline.frame)} -> {len(chaotic.frame)} (unauditable)"
        )
    # Only columns present under the SAME name in both frames are cell-auditable. A
    # column that was dropped/renamed (not "common") is handled by the structural check;
    # a value fault recorded against such a column is excused here — the frame diff cannot
    # follow the structural change, so counting it would false-fail a legitimate combined
    # chain (rename-then-corrupt, corrupt-then-drop).
    # Only columns that are UNIQUE by name in both frames are cell-auditable — a
    # duplicate name makes ``frame[col]`` a DataFrame (the diff would be ambiguous).
    base_cols = list(baseline.frame.columns)
    chao_cols = list(chaotic.frame.columns)
    common = {
        c
        for c in base_cols
        if c in chao_cols and base_cols.count(c) == 1 and chao_cols.count(c) == 1
    }
    n = min(len(baseline.frame), len(chaotic.frame))
    present: set[tuple[int, str]] = set()
    for col in common:
        b = baseline.frame[col]
        c = chaotic.frame[col]
        b_na = b.isna().to_numpy()
        c_na = c.isna().to_numpy()
        ba = b.to_numpy(dtype=object)
        ca = c.to_numpy(dtype=object)
        for i in range(n):
            if b_na[i] and c_na[i]:
                continue
            if b_na[i] != c_na[i] or ba[i] != ca[i]:
                present.add((i, col))

    # (row, column) -> recorded value; a non-integer row is itself a manifest defect.
    listed: dict[tuple[int, str], str] = {}
    for entry in manifest.entries:
        if entry.get("fault_type") in _STRUCTURAL or "row" not in entry or "column" not in entry:
            continue
        if entry["column"] not in common:
            continue  # column was structurally changed; audited by _audit_structural
        try:
            row = int(entry["row"])
        except (TypeError, ValueError):
            listed_not_present.append(f"manifest entry has a non-integer row {entry.get('row')!r}")
            continue
        listed[(row, entry["column"])] = str(entry.get("value", ""))

    listed_keys = set(listed)
    for row, col in sorted(present - listed_keys):
        present_not_listed.append(f"row {row} column {col!r} changed but not in the manifest")
    for row, col in sorted(listed_keys - present):
        # A listed cell that did not change is still "present" if it holds the recorded
        # value — a fault that injected a value equal to the original (e.g. duplicate_keys
        # copying an existing value) materialised, it just isn't visible as a diff.
        if _holds_recorded_value(chaotic, row, col, listed[(row, col)]):
            continue
        listed_not_present.append(f"row {row} column {col!r} listed but not present in output")
    return len(present)


def _holds_recorded_value(chaotic: Dataset, row: int, col: str, recorded: str) -> bool:
    if col not in chaotic.frame.columns or not 0 <= row < len(chaotic.frame):
        return False
    cell = chaotic.frame[col].iloc[row]
    return str(cell) == recorded or repr(cell)[:80] == recorded
