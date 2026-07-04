"""File exporters — CSV / Parquet / JSON (Story 2.6).

Each exporter serializes a Dataset from its canonical ``Schema`` (via
``normalize_for_export``), so the *declared* logical type is what lands on disk,
not whatever pandas dtype the generator produced (AR-10). Output is **deterministic**
— byte-identical for the same Dataset — so a fixed Profile + seed + config yields a
reproducible artifact (NFR-4): fixed Schema-driven column order, ISO-8601 datetimes,
no row index, and (Parquet) a version-stable footer.

Structurally satisfy the ``tymi.ports.Exporter`` Protocol. ``render`` returns the
serialized payload (used for stdout); ``export`` writes it to a path.
"""

from __future__ import annotations

import io
from pathlib import Path

from tymi.core.errors import ExportError
from tymi.domain.artifacts import Dataset
from tymi.io.schema_map import normalize_for_export


class CsvExporter:
    """Deterministic CSV (UTF-8, no index, full-precision datetimes)."""

    binary = False

    def render(self, dataset: Dataset) -> str:
        # Default date rendering preserves sub-second precision (no truncation) and
        # full float repr, so the CSV is a faithful, re-importable copy of the data.
        return normalize_for_export(dataset).to_csv(index=False)

    def export(self, dataset: Dataset, *, target: str) -> None:
        _write_text(target, self.render(dataset))


class JsonExporter:
    """Deterministic JSON — a list of row objects, ISO-8601 datetimes, null for NA.

    ``double_precision=15`` keeps floats near-faithful (pandas' default of 10 would
    silently truncate to 10 significant digits) — note 15 is pandas' hard cap, one or
    two digits short of a full 17-significant-digit round-trip, so JSON is marginally
    lossier than CSV/Parquet for a few values. ``date_unit="ns"`` preserves sub-second
    datetimes. For an exact float round-trip use CSV or Parquet.
    """

    binary = False

    def render(self, dataset: Dataset) -> str:
        return normalize_for_export(dataset).to_json(
            orient="records", date_format="iso", date_unit="ns", double_precision=15
        )

    def export(self, dataset: Dataset, *, target: str) -> None:
        _write_text(target, self.render(dataset))


class ParquetExporter:
    """Deterministic Parquet via pyarrow (byte-identical for a fixed pyarrow version)."""

    binary = True

    def render(self, dataset: Dataset) -> bytes:
        buffer = io.BytesIO()
        try:
            normalize_for_export(dataset).to_parquet(buffer, engine="pyarrow", index=False)
        except ImportError as exc:  # pyarrow missing
            raise ExportError(
                "Parquet export requires the 'pyarrow' package to be installed."
            ) from exc
        return buffer.getvalue()

    def export(self, dataset: Dataset, *, target: str) -> None:
        _write_bytes(target, self.render(dataset))


#: Registered file formats. ``sql`` is handled by the engine loader, not here.
_EXPORTERS = {
    "csv": CsvExporter,
    "json": JsonExporter,
    "parquet": ParquetExporter,
}

FILE_FORMATS = tuple(_EXPORTERS)


def get_exporter(fmt: str):
    """Return an exporter for ``fmt`` (``csv``/``json``/``parquet``) or raise."""
    exporter_cls = _EXPORTERS.get(fmt.lower())
    if exporter_cls is None:
        raise ExportError(
            f"Unknown export format {fmt!r}. Available: {sorted(_EXPORTERS)} (or 'sql')."
        )
    return exporter_cls()


def _write_text(target: str | Path, payload: str) -> None:
    try:
        Path(target).write_text(payload, encoding="utf-8")
    except OSError as exc:
        raise ExportError(f"Could not write {target}: {exc}") from exc


def _write_bytes(target: str | Path, payload: bytes) -> None:
    try:
        Path(target).write_bytes(payload)
    except OSError as exc:
        raise ExportError(f"Could not write {target}: {exc}") from exc
