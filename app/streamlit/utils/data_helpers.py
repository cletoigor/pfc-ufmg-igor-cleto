import streamlit as st
import pandas as pd
import duckdb
import os

# Relative to this file (app/streamlit/utils/data_helpers.py)
# to reach app/data/staging
STAGING_DATA_PATH = "../../data/staging" 

def load_data(start_date, end_date, selected_devices=None):
    """
    Loads data from partitioned Parquet files in the staging directory
    using DuckDB, filtered by date and optionally by device.
    """
    script_dir = os.path.dirname(__file__)
    abs_staging_path = os.path.abspath(os.path.join(script_dir, STAGING_DATA_PATH))

    query_parts = []
    params = []

    base_query = f"FROM read_parquet('{os.path.join(abs_staging_path, '**', '*.parquet')}', hive_partitioning=1) WHERE 1=1"
    query_parts.append(base_query)

    if start_date:
        query_parts.append("AND event_date >= ?")
        params.append(start_date.strftime('%Y-%m-%d'))
    if end_date:
        query_parts.append("AND event_date <= ?")
        params.append(end_date.strftime('%Y-%m-%d'))

    if selected_devices:
        device_placeholders = ', '.join(['?'] * len(selected_devices))
        query_parts.append(f"AND device_name IN ({device_placeholders})")
        params.extend(selected_devices)

    query_parts.append("AND code IN ('cur_power', 'cur_current', 'cur_voltage', 'fault')")

    full_query = f"""
    SELECT
        code,
        value,
        device_id,
        event_time,
        device_name,
        event_date,
        filename
    { ' '.join(query_parts) }
    ORDER BY event_time ASC
    """

    try:
        with duckdb.connect(database=':memory:', read_only=False) as con:
            df = con.execute(full_query, params).fetchdf()

        if df.empty:
            return pd.DataFrame()

        df['event_time'] = pd.to_datetime(df['event_time'])
        df_pivot = df.pivot_table(index=['event_time', 'device_id', 'device_name', 'event_date', 'filename'],
                                  columns='code',
                                  values='value',
                                  aggfunc='first').reset_index()

        if 'cur_power' in df_pivot.columns:
            df_pivot['power_W'] = pd.to_numeric(df_pivot['cur_power'], errors='coerce') / 10.0
        if 'cur_current' in df_pivot.columns:
            df_pivot['current_mA'] = pd.to_numeric(df_pivot['cur_current'], errors='coerce')
        if 'cur_voltage' in df_pivot.columns:
            df_pivot['voltage_V'] = pd.to_numeric(df_pivot['cur_voltage'], errors='coerce') / 10.0
        
        return df_pivot

    except Exception as e:
        st.error(f"Error loading data from data_helpers: {e}") # Added context to error
        st.error(f"Attempted to load from path: {abs_staging_path}")
        return pd.DataFrame()

def get_available_devices(start_date, end_date):
    script_dir = os.path.dirname(__file__)
    abs_staging_path = os.path.abspath(os.path.join(script_dir, STAGING_DATA_PATH))
    
    query = f"""
    SELECT DISTINCT device_name
    FROM read_parquet('{os.path.join(abs_staging_path, '**', '*.parquet')}', hive_partitioning=1)
    WHERE event_date >= ? AND event_date <= ? AND device_name IS NOT NULL
    ORDER BY device_name;
    """
    try:
        with duckdb.connect(database=':memory:', read_only=False) as con:
            devices_df = con.execute(query, [start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')]).fetchdf()
        return devices_df['device_name'].tolist()
    except Exception as e:
        # Consider logging this error or making it more visible if needed
        # st.warning(f"Could not fetch device list from data_helpers: {e}")
        return []
