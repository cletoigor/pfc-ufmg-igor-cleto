"""
Resource definitions shared across the Dagster code location.
"""
import os

from dagster_duckdb import DuckDBResource

# --- Persistent DuckDB warehouse ---
# The database file lives at app/data/warehouse.duckdb (relative to this file's
# directory, i.e. app/). Dagster (this process) is the sole writer of this file
# via the asset graph below.
#
# IMPORTANT: any *other* process that opens this file (the AI agent, the Streamlit
# dashboard, ad-hoc analysis, etc.) MUST connect with `read_only=True`
# (e.g. `duckdb.connect(WAREHOUSE_DB_PATH, read_only=True)`). DuckDB only allows a
# single read/write connection to a database file at a time; a second writer would
# either fail to connect or block on Dagster's writer, causing lock contention.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
WAREHOUSE_DB_PATH = os.path.join(_APP_DIR, "data", "warehouse.duckdb")

# Ensure the parent directory exists before DuckDB tries to create the file.
os.makedirs(os.path.dirname(WAREHOUSE_DB_PATH), exist_ok=True)

duckdb_resource = DuckDBResource(database=WAREHOUSE_DB_PATH)
