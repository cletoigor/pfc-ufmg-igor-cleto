import streamlit as st
import pandas as pd
import duckdb
import os
from PyPDF2 import PdfReader
import re

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
        original_value, -- Select original_value directly
        metric_value,   -- Also select metric_value
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

        # Create the 'value_for_pivot' column based on 'code'
        # Use 'metric_value' for numeric codes, 'original_value' for others (e.g., 'fault')
        numeric_codes = ['cur_power', 'cur_current', 'cur_voltage', 'add_ele']
        
        # Initialize 'value_for_pivot' with original_value by default
        df['value_for_pivot'] = df['original_value']
        # Where code indicates a numeric metric, use metric_value instead
        # Ensure metric_value is preferred only where it's not NaN (successfully cast)
        df.loc[df['code'].isin(numeric_codes) & df['metric_value'].notna(), 'value_for_pivot'] = df['metric_value']

        df['event_time'] = pd.to_datetime(df['event_time'])
        df_pivot = df.pivot_table(index=['event_time', 'device_id', 'device_name', 'event_date', 'filename'],
                                  columns='code',
                                  values='value_for_pivot',  # Use the new combined column
                                  aggfunc='first').reset_index()

        # Post-pivot processing: Values from metric_value are already numeric.
        if 'cur_power' in df_pivot.columns:
            # cur_power is from metric_value (Watts * 10, based on common Tuya scaling), needs division by 10.0.
            df_pivot['power_W'] = df_pivot['cur_power'] / 10.0
        if 'cur_current' in df_pivot.columns:
            # cur_current is from metric_value (mA), no further scaling needed.
            df_pivot['current_mA'] = df_pivot['cur_current']
        if 'cur_voltage' in df_pivot.columns:
            # cur_voltage is from metric_value (V*10), needs division by 10.0.
            df_pivot['voltage_V'] = df_pivot['cur_voltage'] / 10.0
        
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

def parse_cemig_bill(file_path, password=None):
    """Parse CEMIG PDF bill using PyPDF2 instead of docling"""
    reader = PdfReader(file_path)
    
    if reader.is_encrypted:
        if password:
            reader.decrypt(password)
        else:
            raise ValueError("PDF is encrypted but no password provided")

    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"

    # Custom parsing logic for CEMIG bills
    bill_data = {
        "invoice_number": extract_field(r'Número da Fatura\s+(\d+)', text),
        "due_date": extract_field(r'Vencimento\s+(\d{2}/\d{2}/\d{4})', text),
        "total_amount": extract_field(r'Valor a pagar \(R\$\)\s+([\d,.]+)', text),
        "consumption_kwh": extract_field(r'Energia Elétrica\s+\d+\s+([\d,.]+)', text),
        "consumption_days": extract_field(r'Energia Elétrica\s+(\d+)\s+[\d,.]+', text),
        "billing_period": extract_field(r'Vencimento\s+\d{2}/\d{2}/\d{4}\s+(\d{2}/\d{2}/\d{4} a \d{2}/\d{2}/\d{4})', text)
    }
    
    return bill_data

def extract_field(pattern, text):
    match = re.search(pattern, text)
    return match.group(1) if match else None

def generate_report(bill_data):
    """
    Generates a Streamlit report from the parsed bill data.
    """
    if bill_data is None:
        st.warning("Could not parse the bill.")
        return

    st.subheader("CEMIG Bill Report")
    st.write(f"Invoice Number: {bill_data.get('invoice_number', 'N/A')}")
    st.write(f"Due Date: {bill_data.get('due_date', 'N/A')}")
    st.write(f"Total Amount: {bill_data.get('total_amount', 'N/A')}")
    st.write(f"Consumption (kWh): {bill_data.get('consumption_kwh', 'N/A')}")
    st.write(f"Consumption Days: {bill_data.get('consumption_days', 'N/A')}")
    st.write(f"Billing Period: {bill_data.get('billing_period', 'N/A')}")
