import streamlit as st
import pandas as pd
import duckdb
import plotly.express as px
import plotly.graph_objects as go # Added for CUSUM chart
import os
from datetime import datetime, time
import numpy as np # Added for CUSUM calculations

# --- Configuration ---
STAGING_DATA_PATH = "data/staging" # Relative to the app directory

# --- Helper Functions ---

def load_data(start_date, end_date, selected_devices=None):
    """
    Loads data from partitioned Parquet files in the staging directory
    using DuckDB, filtered by date and optionally by device.
    """
    script_dir = os.path.dirname(__file__)
    abs_staging_path = os.path.abspath(os.path.join(script_dir, STAGING_DATA_PATH))

    query_parts = []
    params = []

    # Base query
    base_query = f"FROM read_parquet('{os.path.join(abs_staging_path, '**', '*.parquet')}', hive_partitioning=1) WHERE 1=1"
    query_parts.append(base_query)

    # Date filtering
    if start_date:
        query_parts.append("AND event_date >= ?")
        params.append(start_date.strftime('%Y-%m-%d'))
    if end_date:
        query_parts.append("AND event_date <= ?")
        params.append(end_date.strftime('%Y-%m-%d'))

    # Device filtering
    if selected_devices:
        # Create placeholders for each selected device
        device_placeholders = ', '.join(['?'] * len(selected_devices))
        query_parts.append(f"AND device_name IN ({device_placeholders})")
        params.extend(selected_devices)

    # Select specific codes for initial load, can be expanded later
    query_parts.append("AND code IN ('cur_power', 'cur_current', 'cur_voltage', 'fault')")

    # Construct the full query
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
            st.warning(f"No data found for the selected criteria in {abs_staging_path}.")
            return pd.DataFrame()

        # Data type conversions and transformations
        df['event_time'] = pd.to_datetime(df['event_time'])

        # Create specific columns based on 'code'
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
        # 'fault' column will retain its original values (string type)

        return df_pivot

    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.error(f"Attempted query: {full_query} with params: {params}")
        st.error(f"Please ensure your staging data path is correct: {abs_staging_path} and contains valid Parquet files.")
        return pd.DataFrame()

def get_available_devices(start_date, end_date):
    """
    Gets a list of available device names from the data within the date range.
    """
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
        st.warning(f"Could not fetch device list: {e}")
        return []

# --- Streamlit App UI ---
st.set_page_config(layout="wide") # Must be the first Streamlit command

st.title("Análise de Consumo de Energia de Dispositivos Domésticos")

# --- Sidebar ---
st.sidebar.header("Filtros")

# Date Range Selector
# Default to last 7 days
default_end_date = datetime.now().date()
default_start_date = default_end_date - pd.Timedelta(days=6)

start_date = st.sidebar.date_input("Data Inicial", value=default_start_date)
end_date = st.sidebar.date_input("Data Final", value=default_end_date)

# Device Selector - populated after loading initial device list
available_devices = []
if start_date and end_date and start_date <= end_date:
    available_devices = get_available_devices(start_date, end_date)
else:
    st.sidebar.warning("Datas inválidas. Data inicial deve ser anterior ou igual à data final.")

selected_devices = []
if available_devices:
    selected_devices = st.sidebar.multiselect(
        "Selecione os Dispositivos",
        options=available_devices,
        default=available_devices[:1] # Default to the first device if available
    )
else:
    st.sidebar.info("Nenhum dispositivo encontrado para o período selecionado ou dados não disponíveis.")


# --- Load Data based on filters ---
data_df = pd.DataFrame()
if start_date and end_date and start_date <= end_date and selected_devices:
    data_df = load_data(start_date, end_date, selected_devices)
elif not selected_devices and available_devices:
    st.info("Por favor, selecione pelo menos um dispositivo para visualizar os dados.")
elif not available_devices:
    st.info("Nenhum dado de dispositivo disponível para carregar com os filtros atuais.")


# --- Main Area Tabs ---
tab1, tab2, tab3 = st.tabs([
    "Visão Geral da Potência",
    "Perfil de Potência (Análise Multicanal)",
    "Controle Estatístico de Processo (CEP/SPC)"
])

with tab1:
    st.header("Visão Geral da Potência")
    if not data_df.empty and 'power_W' in data_df.columns:
        st.subheader("Indicadores Chave (por dispositivo)")
        for device in selected_devices:
            device_data = data_df[data_df['device_name'] == device]
            if not device_data.empty:
                st.markdown(f"**{device}**")
                avg_power = device_data['power_W'].mean()
                max_power = device_data['power_W'].max()
                min_power = device_data['power_W'].min()
                
                # Estimate energy consumed (Wh) by integrating power over time
                # Sort by time to ensure correct calculation
                device_data = device_data.sort_values(by='event_time')
                device_data['time_diff_hours'] = device_data['event_time'].diff().dt.total_seconds().fillna(0) / 3600.0
                # Power is instantaneous, assume it's constant over the interval to the next point
                # For the first point, time_diff is 0, so energy contribution is 0.
                # This is a trapezoidal-like rule if intervals are regular, or Riemann sum for irregular.
                # More accurate would be to know the sampling interval.
                # For now, let's use a simple sum of (power * time_interval_to_next_point)
                # We'll use the power at the start of the interval.
                
                # Calculate energy for each interval: power_W * time_diff_hours
                # Shift power_W to align with the start of the interval for which time_diff_hours is calculated
                # (time_diff_hours at row i is the duration from row i-1 to row i)
                # So, energy in interval i is power_W[i-1] * time_diff_hours[i]
                
                # A simpler approach for now: sum of (power * (fixed_interval_if_known or estimated_interval))
                # Assuming data points are frequent enough, sum(P_avg_between_points * delta_t)
                # If we assume power_W is average power over the interval leading to this timestamp:
                # total_energy_Wh = (device_data['power_W'] * device_data['time_diff_hours']).sum()
                
                # Let's calculate energy based on the average power and total duration for simplicity first
                # This is a rough estimate.
                total_duration_hours = (device_data['event_time'].max() - device_data['event_time'].min()).total_seconds() / 3600.0
                if total_duration_hours > 0:
                    estimated_energy_Wh = avg_power * total_duration_hours
                    estimated_energy_kWh = estimated_energy_Wh / 1000.0
                else:
                    estimated_energy_Wh = 0
                    estimated_energy_kWh = 0

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Potência Média", f"{avg_power:.2f} W")
                col2.metric("Potência Máxima", f"{max_power:.2f} W")
                col3.metric("Potência Mínima", f"{min_power:.2f} W")
                if total_duration_hours > 0:
                     col4.metric("Energia Estimada", f"{estimated_energy_kWh:.3f} kWh")
                else:
                    col4.metric("Energia Estimada", "N/A (duração curta)")
                st.divider()

        st.subheader("Gráfico de Série Temporal da Potência (W)")
        if not data_df.empty:
            fig_power_ts = px.line(data_df, x='event_time', y='power_W', color='device_name',
                                   labels={'event_time': 'Tempo', 'power_W': 'Potência (W)', 'device_name': 'Dispositivo'},
                                   title="Potência Instantânea ao Longo do Tempo")
            st.plotly_chart(fig_power_ts, use_container_width=True)
        else:
            st.info("Nenhum dado de potência para exibir.")

        st.subheader("Distribuição da Potência (W)")
        if not data_df.empty:
            fig_power_dist = px.box(data_df, x='device_name', y='power_W', color='device_name',
                                    labels={'device_name': 'Dispositivo', 'power_W': 'Potência (W)'},
                                    title="Distribuição da Potência por Dispositivo")
            st.plotly_chart(fig_power_dist, use_container_width=True)
        else:
            st.info("Nenhum dado de potência para exibir a distribuição.")
    elif data_df.empty:
        st.info("Nenhum dado carregado para os filtros selecionados.")
    else:
        st.warning("Coluna 'power_W' não encontrada nos dados processados. Verifique a transformação dos dados.")


with tab2:
    st.header("Perfil de Potência (Análise Multicanal)")
    if not data_df.empty and 'power_W' in data_df.columns:
        # 1. Add hour of day and day of week columns
        data_df['hour_of_day'] = data_df['event_time'].dt.hour
        data_df['day_of_week'] = data_df['event_time'].dt.day_name(locale='pt_BR.UTF-8') # For Portuguese day names
        # Order days of week correctly
        days_ordered = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
        data_df['day_of_week'] = pd.Categorical(data_df['day_of_week'], categories=days_ordered, ordered=True)

        # 2. Group by device, day_of_week, hour_of_day and calculate mean and std dev power
        # Explicitly use observed=False for groupby with categorical data to avoid FutureWarnings and ensure all categories are present
        profile_df = data_df.groupby(['device_name', 'day_of_week', 'hour_of_day'], observed=False)['power_W'].agg(['mean', 'std', 'min', 'max', 'median']).reset_index()
        profile_df.rename(columns={'mean': 'power_mean_W', 'std': 'power_std_W', 'min': 'power_min_W', 'max': 'power_max_W', 'median': 'power_median_W'}, inplace=True)

        st.subheader("Estatísticas Descritivas do Perfil de Potência")
        st.write("Estatísticas agregadas por dispositivo, dia da semana e hora do dia.")
        st.dataframe(profile_df)

        st.subheader("Perfil Médio de Potência por Hora do Dia (Agregado)")
        # Aggregate across all selected days for a general hourly profile per device
        # For hour_of_day, observed=True (default future behavior) is fine as it's not categorical here.
        hourly_avg_profile = data_df.groupby(['device_name', 'hour_of_day'])['power_W'].mean().reset_index()
        
        fig_hourly_avg = px.line(hourly_avg_profile, x='hour_of_day', y='power_W', color='device_name',
                                 labels={'hour_of_day': 'Hora do Dia', 'power_W': 'Potência Média (W)'},
                                 title="Perfil Médio de Potência por Hora do Dia (Todos os Dias Selecionados)")
        st.plotly_chart(fig_hourly_avg, use_container_width=True)

        st.subheader("Variabilidade do Perfil de Potência por Hora do Dia")
        st.write("Distribuição da potência para cada hora do dia, por dispositivo.")
        fig_hourly_box = px.box(data_df, x='hour_of_day', y='power_W', color='device_name',
                                labels={'hour_of_day': 'Hora do Dia', 'power_W': 'Potência (W)', 'device_name': 'Dispositivo'},
                                title="Distribuição da Potência por Hora do Dia e Dispositivo")
        st.plotly_chart(fig_hourly_box, use_container_width=True)

        st.subheader("Variabilidade do Perfil de Potência por Dia da Semana")
        st.write("Distribuição da potência para cada dia da semana, por dispositivo.")
        fig_daily_box = px.box(data_df, x='day_of_week', y='power_W', color='device_name',
                               labels={'day_of_week': 'Dia da Semana', 'power_W': 'Potência (W)', 'device_name': 'Dispositivo'},
                               category_orders={"day_of_week": days_ordered}, # Ensure correct order
                               title="Distribuição da Potência por Dia da Semana e Dispositivo")
        st.plotly_chart(fig_daily_box, use_container_width=True)


        st.subheader("Perfil Detalhado de Potência (Heatmap)")
        for device in selected_devices:
            device_profile_data = profile_df[profile_df['device_name'] == device]
            if not device_profile_data.empty:
                st.markdown(f"**{device}**")
                # Explicitly use observed=False for pivot_table with categorical index
                heatmap_data_pivoted = device_profile_data.pivot_table(index='day_of_week', columns='hour_of_day', values='power_mean_W', observed=False)
                # Reindex to ensure all days are present in the correct order for imshow, fill missing with NaN
                heatmap_data = heatmap_data_pivoted.reindex(index=days_ordered, columns=list(range(24)))
                
                if not heatmap_data.empty:
                    fig_heatmap = px.imshow(heatmap_data,
                                            labels=dict(x="Hora do Dia", y="Dia da Semana", color="Potência Média (W)"),
                                            x=heatmap_data.columns, 
                                            y=heatmap_data.index,   
                                            title=f"Heatmap do Perfil de Potência para {device}",
                                            aspect="auto")
                    fig_heatmap.update_xaxes(tickvals=list(range(0,24,2)), dtick=2) 
                    st.plotly_chart(fig_heatmap, use_container_width=True)
                else:
                    st.info(f"Não foi possível gerar o heatmap para {device} (dados de perfil vazios após pivotar/reindexar).")
            else:
                st.info(f"Nenhum dado de perfil para o dispositivo {device}.")
    else:
        st.info("Carregue os dados e selecione dispositivos para ver o Perfil de Potência.")


with tab3:
    st.header("Controle Estatístico de Processo (CEP/SPC)")
    if not data_df.empty and 'power_W' in data_df.columns and selected_devices:
        st.subheader("Gráfico CUSUM para Detecção de Mudanças na Potência")

        # Device selection for CUSUM chart (univariate)
        cusum_device = st.selectbox("Selecione um dispositivo para o gráfico CUSUM:", selected_devices)

        if cusum_device:
            device_cusum_data = data_df[data_df['device_name'] == cusum_device].copy()
            device_cusum_data.sort_values(by='event_time', inplace=True)
            
            if len(device_cusum_data) < 2:
                st.warning("Dados insuficientes para o dispositivo selecionado para gerar o gráfico CUSUM.")
            else:
                # Parameters for CUSUM
                st.markdown("**Parâmetros do CUSUM:**")
                
                # Reference period for mu and sigma calculation
                # Ensure reference dates are within the overall selected date range
                min_date = data_df['event_time'].min().date()
                max_date = data_df['event_time'].max().date()

                ref_start_date = st.date_input("Data Inicial de Referência (para μ, σ):", 
                                               value=min_date, 
                                               min_value=min_date, max_value=max_date)
                ref_end_date = st.date_input("Data Final de Referência (para μ, σ):", 
                                             value=min_date + pd.Timedelta(days=min(6, (max_date - min_date).days)), # Default to a week or less
                                             min_value=min_date, max_value=max_date)

                # CUSUM parameters nu (allowance/drift) and h (threshold)
                # These are based on the article's CUSUM for squared residuals
                # For power_W, residuals are power_W - mu. Squared residuals are (power_W - mu)^2
                
                # Calculate mu and sigma from the reference period
                ref_data = device_cusum_data[
                    (device_cusum_data['event_time'].dt.date >= ref_start_date) &
                    (device_cusum_data['event_time'].dt.date <= ref_end_date)
                ]['power_W']

                if not ref_data.empty and len(ref_data) > 1:
                    mu = ref_data.mean()
                    sigma_residuals = ref_data.std() # Std of the power_W in reference period
                    st.write(f"Média de Referência (μ): {mu:.2f} W")
                    st.write(f"Desvio Padrão de Referência (σ_res): {sigma_residuals:.2f} W")

                    # Heuristics for nu and h, user can adjust
                    # nu is an allowance for squared residuals. Let's use (0.5 * sigma_residuals)^2 as a starting point
                    # h is a threshold for the sum of squared residuals. Let's use (5 * sigma_residuals)^2 as a starting point
                    default_nu = (0.5 * sigma_residuals)**2 if sigma_residuals > 0 else 1.0
                    default_h = (5 * sigma_residuals)**2 if sigma_residuals > 0 else 25.0
                    
                    # Ensure nu and h are not extremely small if sigma_residuals is tiny
                    default_nu = max(default_nu, 0.01)
                    default_h = max(default_h, 0.1)


                    param_col1, param_col2 = st.columns(2)
                    nu_cusum = param_col1.number_input("Parâmetro ν (allowance para s_j,i):", 
                                                       min_value=0.0, value=default_nu, step=max(0.01, default_nu/10), format="%.2f")
                    h_cusum = param_col2.number_input("Limite h (threshold para g_j,i):", 
                                                      min_value=0.0, value=default_h, step=max(0.1, default_h/10), format="%.2f")

                    # Calculate CUSUM statistic (g_j,i) based on the article's method
                    # Using power_W for V(VMV) and mu for X_hat
                    residuals = device_cusum_data['power_W'] - mu
                    s_ji = residuals**2
                    
                    g_ji = np.zeros(len(s_ji))
                    alarms = np.zeros(len(s_ji), dtype=bool)

                    if len(s_ji) > 0:
                        g_ji[0] = max(0, s_ji.iloc[0] - nu_cusum)
                        if g_ji[0] > h_cusum:
                            alarms[0] = True
                            # g_ji[0] = 0 # Reset after alarm as per article's Eq. (4.7) - optional, can make it harder to see sustained issues

                    for t in range(1, len(s_ji)):
                        g_ji[t] = max(0, g_ji[t-1] + s_ji.iloc[t] - nu_cusum)
                        if g_ji[t] > h_cusum:
                            alarms[t] = True
                            # g_ji[t] = 0 # Optional reset

                    device_cusum_data['cusum_g'] = g_ji
                    device_cusum_data['alarm'] = alarms
                    
                    # Plot CUSUM
                    fig_cusum = go.Figure() # Removed template from layout
                    fig_cusum.add_trace(go.Scatter(x=device_cusum_data['event_time'], y=device_cusum_data['cusum_g'],
                                                   mode='lines', name='CUSUM (g_j,i)'))
                    fig_cusum.add_hline(y=h_cusum, line_dash="dash", line_color="red", name=f"Limite h = {h_cusum:.2f}")

                    # Add alarm points
                    alarm_points = device_cusum_data[device_cusum_data['alarm']]
                    fig_cusum.add_trace(go.Scatter(x=alarm_points['event_time'], y=alarm_points['cusum_g'],
                                                   mode='markers', name='Alarme', marker=dict(color='red', size=8)))

                    fig_cusum.update_layout(title=f"Gráfico CUSUM para {cusum_device}",
                                            xaxis_title="Tempo", yaxis_title="Estatística CUSUM (g_j,i)")
                    st.plotly_chart(fig_cusum, use_container_width=True)

                elif not ref_data.empty and len(ref_data) <=1:
                    st.warning("Período de referência muito curto para calcular σ (precisa de >1 ponto).")
                else:
                    st.warning("Nenhum dado no período de referência selecionado para calcular μ e σ.")
        
        # Fault monitoring (existing code)
        if 'fault' in data_df.columns and not data_df[data_df['fault'].notna()].empty:
            st.subheader("Registros de Falha")
            # Filter for the selected CUSUM device if one is chosen, otherwise show all
            fault_display_data = data_df
            if cusum_device:
                fault_display_data = data_df[data_df['device_name'] == cusum_device]
            
            fault_data_filtered = fault_display_data[fault_display_data['fault'].notna()][['event_time', 'device_name', 'fault']].copy()
            if not fault_data_filtered.empty:
                fault_data_filtered['fault_description'] = fault_data_filtered['fault'].apply(lambda x: x if isinstance(x, str) else str(x)) # Ensure string
                st.dataframe(fault_data_filtered)
            else:
                st.info(f"Nenhum registro de falha encontrado para {cusum_device} no período selecionado.")
        else:
            st.info("Nenhum registro de falha encontrado no período selecionado para os dispositivos filtrados.")
            
    elif not selected_devices:
        st.info("Por favor, selecione um dispositivo na barra lateral para ver o CEP/SPC.")
    else: # data_df is empty or no power_W
        st.info("Carregue os dados e selecione dispositivos para ver o CEP/SPC.")

st.sidebar.markdown("---")
st.sidebar.info("Desenvolvido por Igor Cleto.")
