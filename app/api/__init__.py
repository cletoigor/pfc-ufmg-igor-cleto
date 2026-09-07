"""Framework-free backend for the web UI (see docs/api_contract.md).

`app.api.data_access` holds the data-loading/formatting logic (no Streamlit
import — it is shared by both the Starlette app in `app.api.server` and the
Streamlit dashboard in `app.dashboard.dashboard`). `app.api.server` wires it
into HTTP routes.
"""
