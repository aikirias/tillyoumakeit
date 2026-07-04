"""UI controller logic (Story 5.1+).

Pure functions the Streamlit view (``app.py``) calls. Kept free of any ``streamlit``
import so they are unit-testable without a browser and so the view stays a thin shell.
Every function takes/returns plain artifacts (the shared :class:`Config`, dataclasses),
and the engine registry is injectable so tests use a fake adapter with no live database.
"""

from __future__ import annotations

from dataclasses import dataclass

from tymi.config.models import Config, ConnectionConfig, SourceConfig
from tymi.core.errors import EngineConnectionError, TymiError
from tymi.core.plugins import load_engines

#: Engines selectable in the connection form (the four AD-2 adapters).
ENGINES = ("mssql", "postgres", "mysql", "starrocks")


@dataclass(frozen=True)
class ConnectionResult:
    """Outcome of a connection test — never carries a raw credential."""

    ok: bool
    message: str


def default_config() -> Config:
    """A fresh Config for a new UI session (the shared, mutable-by-copy artifact)."""
    return Config()


def set_connection(
    config: Config,
    *,
    engine: str,
    host: str,
    port: int | None = None,
    database: str | None = None,
    user_env: str = "TYMI_DB_USER",
    password_env: str = "TYMI_DB_PASSWORD",
) -> Config:
    """Return a copy of ``config`` with its source engine + connection set.

    Only the *names* of the env vars holding credentials are stored (NFR-6). Pydantic
    validates the connection (e.g. port range), raising ``pydantic.ValidationError`` (a
    ``ValueError``) on bad input.
    """
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}; expected one of {ENGINES}")
    # Normalise here (single source of truth for both the UI form and direct callers): a
    # blank host is a meaningless connection and must not save as a silent success; blank
    # optional fields collapse to None / the documented env-var defaults.
    host = host.strip()
    if not host:
        raise ValueError("host must not be empty")
    connection = ConnectionConfig(
        host=host,
        port=port,
        database=(database or "").strip() or None,
        user_env=(user_env or "").strip() or "TYMI_DB_USER",
        password_env=(password_env or "").strip() or "TYMI_DB_PASSWORD",
    )
    source = config.source.model_copy(update={"engine": engine, "connection": connection})
    return config.model_copy(update={"source": source})


def connection_summary(config: Config) -> dict[str, object] | None:
    """Display-safe view of the configured connection — env-var *names*, never secrets."""
    source = config.source
    conn = source.connection
    if source.engine is None or conn is None:
        return None
    return {
        "engine": source.engine,
        "host": conn.host,
        "port": conn.port,
        "database": conn.database,
        "user_env": conn.user_env,
        "password_env": conn.password_env,
    }


def test_connection(
    config: Config, *, engines: dict[str, type] | None = None
) -> ConnectionResult:
    """Build the configured engine adapter in-process and test it.

    ``engines`` overrides the entry-point registry (tests inject a fake adapter). The
    returned message never contains a credential — only the connection error text, which
    the adapters are contracted to keep secret-free (NFR-6).
    """
    source = config.source
    if source.engine is None or source.connection is None:
        return ConnectionResult(False, "No connection configured yet.")
    registry = engines if engines is not None else load_engines()
    adapter_cls = registry.get(source.engine)
    if adapter_cls is None:
        return ConnectionResult(
            False, f"Unknown engine {source.engine!r}. Available: {sorted(registry)}"
        )
    try:
        adapter_cls(source.connection).test_connection()
    except EngineConnectionError as exc:
        return ConnectionResult(False, f"Connection failed: {exc}")
    except TymiError as exc:  # any typed adapter/config error, surfaced cleanly (scrubbed upstream)
        return ConnectionResult(False, str(exc))
    except Exception:  # noqa: BLE001 - a misbehaving 3rd-party adapter: don't echo a raw
        # driver traceback (it can carry a DSN/password) — return a generic message (NFR-6).
        return ConnectionResult(False, "Connection test failed with an unexpected adapter error.")
    return ConnectionResult(True, f"Connection to {source.engine!r} OK.")


__all__ = [
    "ENGINES",
    "ConnectionResult",
    "Config",
    "SourceConfig",
    "default_config",
    "set_connection",
    "connection_summary",
    "test_connection",
]
