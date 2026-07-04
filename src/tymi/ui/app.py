"""Streamlit app — the TYMI wizard (driving adapter, Story 5.1+).

A thin view over :mod:`tymi.ui.services`: it renders forms and delegates every action to a
pure service function. The one shared :class:`~tymi.config.models.Config` lives in
``st.session_state`` so all steps read/write the same artifact (AD-8 CLI↔UI parity).

Streamlit executes this file top-to-bottom; ``main()`` runs at import so
``streamlit.testing.v1.AppTest`` can drive it headlessly.
"""

from __future__ import annotations

import streamlit as st

from tymi.ui import services

#: Wizard steps shown in the sidebar. Steps past Connection are filled in 5.2–5.5.
STEPS = ("Connection", "Profile", "Generate", "Chaos", "Reports")
_PLACEHOLDER = {
    "Profile": "Profile & schema explorer — Story 5.2.",
    "Generate": "Faithful generation config & preview — Story 5.3.",
    "Chaos": "Chaos policy config & preview — Story 5.4.",
    "Reports": "Reports view & export — Story 5.5.",
}


def _config() -> services.Config:
    """The shared session Config, created once per session."""
    if "config" not in st.session_state:
        st.session_state["config"] = services.default_config()
    return st.session_state["config"]


def render_connection() -> None:
    """Connection form: engine + host/port/db + credential env-var *names* (NFR-6)."""
    st.header("Connection")
    st.caption(
        "Only the *names* of the environment variables holding your credentials are "
        "stored — never the username or password itself."
    )
    config = _config()
    summary = services.connection_summary(config)

    with st.form("connection_form"):
        engine = st.selectbox("Engine", services.ENGINES)
        host = st.text_input("Host", value="localhost")
        port = st.number_input("Port (0 = default)", min_value=0, max_value=65535, value=0)
        database = st.text_input("Database", value="")
        user_env = st.text_input("Username env var", value="TYMI_DB_USER")
        password_env = st.text_input("Password env var", value="TYMI_DB_PASSWORD")
        saved = st.form_submit_button("Save connection")

    if saved:
        try:
            st.session_state["config"] = services.set_connection(
                config,
                engine=engine,
                host=host,
                port=int(port) or None,
                database=database or None,
                user_env=user_env,
                password_env=password_env,
            )
            st.success(f"Saved connection to {engine!r}.")
            summary = services.connection_summary(st.session_state["config"])
        except Exception as exc:  # noqa: BLE001 - surface any validation error to the user
            st.error(f"Invalid connection: {exc}")

    if summary is not None:
        st.subheader("Current connection")
        st.json(summary)
        if st.button("Test connection", key="test_conn"):
            result = services.test_connection(st.session_state["config"])
            (st.success if result.ok else st.error)(result.message)
    else:
        st.info("No connection configured yet.")


def main() -> None:
    """Render the sidebar wizard and the selected step."""
    st.set_page_config(page_title="TYMI", page_icon="🎲")
    st.title("TYMI — Fake It Till You Make It")
    _config()
    step = st.sidebar.radio("Step", STEPS)
    if step == "Connection":
        render_connection()
    else:
        st.header(step)
        st.info(_PLACEHOLDER[step])


main()
