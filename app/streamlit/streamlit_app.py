import streamlit as st
import pandas as pd
import duckdb
import plotly.express as px
import plotly.graph_objects as go
import os
from datetime import datetime, timedelta # Added timedelta
import numpy as np # Import numpy

# --- Configuration ---
STAGING_DATA_PATH = "../data/staging" # Relative to the app directory

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
        st.error(f"Error loading data: {e}")
        st.error(f"Please ensure your staging data path is correct: {abs_staging_path} and contains valid Parquet files.")
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
        return []

# --- Page Implementations ---
def show_resumo_casa(data_df, selected_devices_list, start_date_filter, end_date_filter):
    st.header("Resumo da Casa")
    st.write(f"Exibindo dados de {start_date_filter.strftime('%d/%m/%Y')} a {end_date_filter.strftime('%d/%m/%Y')}")

    if data_df.empty:
        st.info("Nenhum dado disponível para os filtros selecionados. Ajuste as datas ou dispositivos.")
        return

    st.subheader("Consumo Total de Energia")
    today = datetime.now().date()
    
    data_hoje = data_df[data_df['event_time'].dt.date == today]
    energia_hoje_kwh = 0
    if not data_hoje.empty and 'power_W' in data_hoje.columns:
        for device_name_iter in data_hoje['device_name'].unique():
            device_data_iter = data_hoje[data_hoje['device_name'] == device_name_iter]
            if not device_data_iter.empty and not device_data_iter['power_W'].dropna().empty:
                avg_power_iter = device_data_iter['power_W'].mean()
                min_time_iter = device_data_iter['event_time'].min()
                max_time_iter = device_data_iter['event_time'].max()
                duration_hours_iter = (max_time_iter - min_time_iter).total_seconds() / 3600.0
                if duration_hours_iter > 0:
                    energia_hoje_kwh += (avg_power_iter * duration_hours_iter) / 1000.0

    start_7_days = today - timedelta(days=6)
    data_7_days = data_df[(data_df['event_time'].dt.date >= start_7_days) & (data_df['event_time'].dt.date <= today)]
    energia_7_days_kwh = 0
    if not data_7_days.empty and 'power_W' in data_7_days.columns:
        for device_name_iter in data_7_days['device_name'].unique():
            device_data_iter = data_7_days[data_7_days['device_name'] == device_name_iter]
            if not device_data_iter.empty and not device_data_iter['power_W'].dropna().empty:
                avg_power_iter = device_data_iter['power_W'].mean()
                min_time_iter = device_data_iter['event_time'].min()
                max_time_iter = device_data_iter['event_time'].max()
                duration_hours_iter = (max_time_iter - min_time_iter).total_seconds() / 3600.0
                if duration_hours_iter > 0:
                    energia_7_days_kwh += (avg_power_iter * duration_hours_iter) / 1000.0
    
    start_this_month = today.replace(day=1)
    data_this_month = data_df[(data_df['event_time'].dt.date >= start_this_month) & (data_df['event_time'].dt.date <= today)]
    energia_this_month_kwh = 0
    if not data_this_month.empty and 'power_W' in data_this_month.columns:
        for device_name_iter in data_this_month['device_name'].unique():
            device_data_iter = data_this_month[data_this_month['device_name'] == device_name_iter]
            if not device_data_iter.empty and not device_data_iter['power_W'].dropna().empty:
                avg_power_iter = device_data_iter['power_W'].mean()
                min_time_iter = device_data_iter['event_time'].min()
                max_time_iter = device_data_iter['event_time'].max()
                duration_hours_iter = (max_time_iter - min_time_iter).total_seconds() / 3600.0
                if duration_hours_iter > 0:
                    energia_this_month_kwh += (avg_power_iter * duration_hours_iter) / 1000.0

    col_res1, col_res2, col_res3 = st.columns(3)
    with col_res1:
        st.metric("Hoje (kWh)", f"{energia_hoje_kwh:.2f}" if energia_hoje_kwh > 0 else "0.00")
    with col_res2:
        st.metric("Últimos 7 Dias (kWh)", f"{energia_7_days_kwh:.2f}" if energia_7_days_kwh > 0 else "0.00")
    with col_res3:
        st.metric("Este Mês (kWh)", f"{energia_this_month_kwh:.2f}" if energia_this_month_kwh > 0 else "0.00")
    
    st.markdown("---") # Divider after total consumption metrics

    current_device_energy_global_period = {}
    if not data_df.empty and 'power_W' in data_df.columns:
        for device_name_iter in data_df['device_name'].unique():
            device_data_iter = data_df[data_df['device_name'] == device_name_iter]
            if not device_data_iter.empty and not device_data_iter['power_W'].dropna().empty:
                avg_power_iter = device_data_iter['power_W'].mean()
                min_time_iter = device_data_iter['event_time'].min()
                max_time_iter = device_data_iter['event_time'].max()
                duration_hours_iter = (max_time_iter - min_time_iter).total_seconds() / 3600.0
                if duration_hours_iter > 0:
                    current_device_energy_global_period[device_name_iter] = (avg_power_iter * duration_hours_iter) / 1000.0 
                else:
                    current_device_energy_global_period[device_name_iter] = 0
            else:
                current_device_energy_global_period[device_name_iter] = 0
    
    st.subheader(f"Principais Consumidores ({start_date_filter.strftime('%d/%m')} a {end_date_filter.strftime('%d/%m')})")
    if current_device_energy_global_period:
        sorted_top_consumers = sorted(current_device_energy_global_period.items(), key=lambda item: item[1], reverse=True)
        
        num_to_display = min(len(sorted_top_consumers), 5) 
        if num_to_display > 0:
            top_consumers_df = pd.DataFrame(sorted_top_consumers[:num_to_display], columns=['Dispositivo', 'Consumo (kWh)'])
            
            for index, row in top_consumers_df.iterrows():
                st.markdown(f"- **{row['Dispositivo']}**: {row['Consumo (kWh)']:.2f} kWh")

            if not top_consumers_df.empty:
                fig_top_consumers = px.bar(top_consumers_df, x='Dispositivo', y='Consumo (kWh)',
                                           title="Top Consumidores de Energia",
                                           labels={'Consumo (kWh)': 'Energia Consumida (kWh)'})
                fig_top_consumers.update_layout(xaxis_title="Dispositivo", yaxis_title="Consumo (kWh)")
                st.plotly_chart(fig_top_consumers, use_container_width=True)
        else:
            st.write("Nenhum dado de consumo de dispositivo para exibir os principais consumidores.")
            
    else:
        st.write("Cálculo de consumo por dispositivo não disponível.")
    
    st.markdown("---") # Divider after Principais Consumidores

    if 'power_W' in data_df.columns:
        # st.markdown("---") # Already have one above
        st.subheader("Análise de Potência Consolidada (W)")
        
        total_avg_power = data_df['power_W'].mean()
        total_max_power = data_df['power_W'].max()
        
        total_estimated_energy_kWh = sum(current_device_energy_global_period.values()) if current_device_energy_global_period else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("Potência Média Total", f"{total_avg_power:.2f} W" if not pd.isna(total_avg_power) else "N/A")
        col2.metric("Potência Máxima Total", f"{total_max_power:.2f} W" if not pd.isna(total_max_power) else "N/A")
        col3.metric("Energia Estimada Total", f"{total_estimated_energy_kWh:.3f} kWh" if total_estimated_energy_kWh > 0 else "N/A")

        if current_device_energy_global_period:
            sorted_devices_by_energy = sorted(current_device_energy_global_period.items(), key=lambda item: item[1], reverse=True)
            st.markdown("---")
            st.subheader(f"Consumo de Energia por Dispositivo ({start_date_filter.strftime('%d/%m')} a {end_date_filter.strftime('%d/%m')})")
            for dev, eng in sorted_devices_by_energy:
                st.markdown(f"**{dev}**: {eng:.3f} kWh")
    else:
        st.info("Dados de potência (power_W) não disponíveis para o resumo.")


def show_detalhes_dispositivo(data_df, selected_device_for_detail, start_date_filter, end_date_filter):
    st.header(f"Detalhes do Dispositivo: {selected_device_for_detail if selected_device_for_detail else 'Nenhum Selecionado'}")
    st.write(f"Exibindo dados de {start_date_filter.strftime('%d/%m/%Y')} a {end_date_filter.strftime('%d/%m/%Y')}")

    if data_df.empty: # Add this check early
        st.info("Nenhum dado global carregado. Verifique os filtros gerais ou a disponibilidade de dados.")
        return

    if not selected_device_for_detail:
        st.info("Por favor, selecione um dispositivo na barra lateral para ver os detalhes.")
        return

    device_specific_data = data_df[data_df['device_name'] == selected_device_for_detail]

    if device_specific_data.empty:
        st.warning(f"Nenhum dado encontrado para o dispositivo '{selected_device_for_detail}' nos filtros selecionados.")
        return

    st.subheader(f"Resumo de Consumo: {selected_device_for_detail}")
    
    today_detail = datetime.now().date()
    
    data_hoje_detail = device_specific_data[device_specific_data['event_time'].dt.date == today_detail]
    energia_hoje_detail_kwh = 0
    if not data_hoje_detail.empty and 'power_W' in data_hoje_detail.columns and not data_hoje_detail['power_W'].dropna().empty:
        avg_power_iter = data_hoje_detail['power_W'].mean()
        min_time_iter = data_hoje_detail['event_time'].min()
        max_time_iter = data_hoje_detail['event_time'].max()
        duration_hours_iter = (max_time_iter - min_time_iter).total_seconds() / 3600.0
        if duration_hours_iter > 0:
            energia_hoje_detail_kwh = (avg_power_iter * duration_hours_iter) / 1000.0

    start_7_days_detail = today_detail - timedelta(days=6)
    data_7_days_detail = device_specific_data[(device_specific_data['event_time'].dt.date >= start_7_days_detail) & (device_specific_data['event_time'].dt.date <= today_detail)]
    energia_7_days_detail_kwh = 0
    if not data_7_days_detail.empty and 'power_W' in data_7_days_detail.columns and not data_7_days_detail['power_W'].dropna().empty:
        avg_power_iter = data_7_days_detail['power_W'].mean()
        min_time_iter = data_7_days_detail['event_time'].min()
        max_time_iter = data_7_days_detail['event_time'].max()
        duration_hours_iter = (max_time_iter - min_time_iter).total_seconds() / 3600.0
        if duration_hours_iter > 0:
            energia_7_days_detail_kwh = (avg_power_iter * duration_hours_iter) / 1000.0
            
    start_this_month_detail = today_detail.replace(day=1)
    data_this_month_detail = device_specific_data[(device_specific_data['event_time'].dt.date >= start_this_month_detail) & (device_specific_data['event_time'].dt.date <= today_detail)]
    energia_this_month_detail_kwh = 0
    if not data_this_month_detail.empty and 'power_W' in data_this_month_detail.columns and not data_this_month_detail['power_W'].dropna().empty:
        avg_power_iter = data_this_month_detail['power_W'].mean()
        min_time_iter = data_this_month_detail['event_time'].min()
        max_time_iter = data_this_month_detail['event_time'].max()
        duration_hours_iter = (max_time_iter - min_time_iter).total_seconds() / 3600.0
        if duration_hours_iter > 0:
            energia_this_month_detail_kwh = (avg_power_iter * duration_hours_iter) / 1000.0

    col_det1, col_det2, col_det3 = st.columns(3)
    col_det1.metric("Consumo Hoje (kWh)", f"{energia_hoje_detail_kwh:.2f}" if energia_hoje_detail_kwh > 0 else "0.00")
    col_det2.metric("Consumo Últimos 7 Dias (kWh)", f"{energia_7_days_detail_kwh:.2f}" if energia_7_days_detail_kwh > 0 else "0.00")
    col_det3.metric("Consumo Este Mês (kWh)", f"{energia_this_month_detail_kwh:.2f}" if energia_this_month_detail_kwh > 0 else "0.00")
    
    st.markdown("---")
    
    with st.expander(f"Análise de Potência (W) - {selected_device_for_detail}", expanded=True):
        st.subheader(f"Métricas de Potência ({start_date_filter.strftime('%d/%m')} a {end_date_filter.strftime('%d/%m')})")
        if 'power_W' in device_specific_data.columns and not device_specific_data['power_W'].dropna().empty:
            avg_power = device_specific_data['power_W'].mean()
            max_power = device_specific_data['power_W'].max()
            min_power = device_specific_data['power_W'].min()
            
            total_duration_hours = (device_specific_data['event_time'].max() - device_specific_data['event_time'].min()).total_seconds() / 3600.0
            estimated_energy_kWh_period = 0 
            if total_duration_hours > 0:
                estimated_energy_kWh_period = (avg_power * total_duration_hours) / 1000.0

            col1_p, col2_p, col3_p, col4_p = st.columns(4) 
            col1_p.metric("Potência Média", f"{avg_power:.2f} W")
            col2_p.metric("Potência Máxima", f"{max_power:.2f} W")
            col3_p.metric("Potência Mínima", f"{min_power:.2f} W")
            col4_p.metric("Energia Estimada (período filtrado)", f"{estimated_energy_kWh_period:.3f} kWh" if total_duration_hours > 0 else "N/A")
            
            st.markdown("---")
            st.subheader("Gráfico de Série Temporal da Potência (W)")
            fig_power_ts = px.line(device_specific_data, x='event_time', y='power_W',
                                   labels={'event_time': 'Tempo', 'power_W': 'Potência (W)'},
                                   title=f"Potência de {selected_device_for_detail} ao Longo do Tempo")
            st.plotly_chart(fig_power_ts, use_container_width=True)

            st.markdown("---") 
            st.subheader("Consumo de Energia Diário (kWh)")
            if 'event_date' not in device_specific_data.columns: 
                device_specific_data['event_date'] = device_specific_data['event_time'].dt.date
            
            daily_energy_list = []
            for date_val, group in device_specific_data.groupby(device_specific_data['event_time'].dt.date):
                if not group.empty and not group['power_W'].dropna().empty:
                    avg_power_day = group['power_W'].mean()
                    min_time_day = group['event_time'].min()
                    max_time_day = group['event_time'].max()
                    duration_hours_day = (max_time_day - min_time_day).total_seconds() / 3600.0
                    if duration_hours_day > 0:
                         daily_energy_list.append({'Data': date_val, 'Energia (kWh)': (avg_power_day * duration_hours_day) / 1000.0})
            
            if daily_energy_list:
                daily_energy_df = pd.DataFrame(daily_energy_list)
                daily_energy_df['Data'] = pd.to_datetime(daily_energy_df['Data']) 
                fig_daily_energy = px.line(daily_energy_df, x='Data', y='Energia (kWh)',
                                           title=f"Consumo Diário de Energia de {selected_device_for_detail}",
                                           markers=True)
                st.plotly_chart(fig_daily_energy, use_container_width=True)
            else:
                st.info("Não há dados suficientes para exibir o consumo diário de energia.")

            st.markdown("---") 
            st.subheader("Perfil de Potência Médio por Hora do Dia")
            
            device_specific_data_copy = device_specific_data.copy() 
            device_specific_data_copy['hour_of_day'] = device_specific_data_copy['event_time'].dt.hour
            hourly_avg_power_device = device_specific_data_copy.groupby('hour_of_day')['power_W'].mean().reset_index()
            
            if not hourly_avg_power_device.empty:
                fig_hourly_avg_device = px.line(hourly_avg_power_device, x='hour_of_day', y='power_W',
                                                labels={'hour_of_day': 'Hora do Dia', 'power_W': 'Potência Média (W)'},
                                                title=f"Perfil Médio de Potência Horária para {selected_device_for_detail}",
                                                markers=True)
                fig_hourly_avg_device.update_xaxes(tickvals=list(range(24)), dtick=2) 
                st.plotly_chart(fig_hourly_avg_device, use_container_width=True)
            else:
                st.info("Não há dados suficientes para exibir o perfil de potência horária.")
        else: 
            st.info(f"Dados de potência (power_W) não disponíveis para {selected_device_for_detail}.")

    with st.expander(f"Análise de Tensão (V) - {selected_device_for_detail}", expanded=False):
        if not device_specific_data.empty and 'voltage_V' in device_specific_data.columns and not device_specific_data['voltage_V'].dropna().empty:
            st.subheader("Métricas de Tensão") 
            avg_voltage = device_specific_data['voltage_V'].mean()
            max_voltage = device_specific_data['voltage_V'].max()
            min_voltage = device_specific_data['voltage_V'].min()
            col_v1, col_v2, col_v3 = st.columns(3)
            col_v1.metric("Tensão Média", f"{avg_voltage:.2f} V")
            col_v2.metric("Tensão Máxima", f"{max_voltage:.2f} V")
            col_v3.metric("Tensão Mínima", f"{min_voltage:.2f} V")

            st.subheader("Gráfico de Série Temporal da Tensão (V)")
            fig_voltage_ts = px.line(device_specific_data, x='event_time', y='voltage_V',
                                     labels={'event_time': 'Tempo', 'voltage_V': 'Tensão (V)'},
                                     title=f"Tensão de {selected_device_for_detail} ao Longo do Tempo")
            st.plotly_chart(fig_voltage_ts, use_container_width=True)

            st.subheader("Distribuição da Tensão (V)")
            fig_voltage_dist = px.box(device_specific_data, y='voltage_V',
                                      labels={'voltage_V': 'Tensão (V)'},
                                      title=f"Distribuição da Tensão para {selected_device_for_detail}")
            st.plotly_chart(fig_voltage_dist, use_container_width=True)
        else: 
            st.info(f"Dados de tensão (voltage_V) não disponíveis para {selected_device_for_detail}.")

    with st.expander(f"Análise de Corrente (mA) - {selected_device_for_detail}", expanded=False):
        if not device_specific_data.empty and 'current_mA' in device_specific_data.columns and not device_specific_data['current_mA'].dropna().empty:
            st.subheader("Métricas de Corrente") 
            avg_current = device_specific_data['current_mA'].mean()
            max_current = device_specific_data['current_mA'].max()
            min_current = device_specific_data['current_mA'].min()
            col_c1, col_c2, col_c3 = st.columns(3)
            col_c1.metric("Corrente Média", f"{avg_current:.2f} mA")
            col_c2.metric("Corrente Máxima", f"{max_current:.2f} mA")
            col_c3.metric("Corrente Mínima", f"{min_current:.2f} mA")

            st.subheader("Gráfico de Série Temporal da Corrente (mA)")
            fig_current_ts = px.line(device_specific_data, x='event_time', y='current_mA',
                                     labels={'event_time': 'Tempo', 'current_mA': 'Corrente (mA)'},
                                     title=f"Corrente de {selected_device_for_detail} ao Longo do Tempo")
            st.plotly_chart(fig_current_ts, use_container_width=True)

            st.subheader("Distribuição da Corrente (mA)")
            fig_current_dist = px.box(device_specific_data, y='current_mA',
                                      labels={'current_mA': 'Corrente (mA)'},
                                      title=f"Distribuição da Corrente para {selected_device_for_detail}")
            st.plotly_chart(fig_current_dist, use_container_width=True)
        else:
            st.info(f"Dados de corrente (current_mA) não disponíveis para {selected_device_for_detail}.")


def show_analise_avancada(data_df, selected_devices_list, start_date_filter, end_date_filter):
    st.header("Análise Avançada")
    st.write(f"Exibindo dados de {start_date_filter.strftime('%d/%m/%Y')} a {end_date_filter.strftime('%d/%m/%Y')}")
    # st.write("Esta seção conterá gráficos mais técnicos, como heatmaps de perfil de potência e análises CEP/SPC, se necessário.") # Remove placeholder
    
    if data_df.empty:
        st.info("Nenhum dado disponível para os filtros selecionados.")
        return

    # Peak Power Analysis (already here)
    if 'power_W' in data_df.columns:
        st.subheader("Análise de Picos de Potência (Todos Dispositivos Selecionados)")
        if not data_df.empty: 
            peak_power_analysis = data_df.loc[data_df.groupby('device_name')['power_W'].idxmax()].reset_index()
            peak_power_analysis = peak_power_analysis[['device_name', 'event_time', 'power_W']]
            peak_power_analysis.rename(columns={'event_time': 'Momento do Pico', 'power_W': 'Potência de Pico (W)'}, inplace=True)
            st.dataframe(peak_power_analysis)
        else:
            st.info("Nenhum dado de potência disponível para análise de picos.")
    else:
        st.info("Dados de potência (power_W) não disponíveis para esta análise.")

    st.markdown("---")
    # CEP/SPC Section from old tab3
    st.subheader("Controle Estatístico de Processo (CEP/SPC)")
    if not data_df.empty and 'power_W' in data_df.columns and selected_devices_list:
        st.subheader("Gráfico CUSUM para Detecção de Mudanças na Potência")

        cusum_device = st.selectbox("Selecione um dispositivo para o gráfico CUSUM:", selected_devices_list, key="cusum_device_avancada")

        if cusum_device:
            device_cusum_data_for_chart = data_df[data_df['device_name'] == cusum_device].copy()
            device_cusum_data_for_chart.sort_values(by='event_time', inplace=True)
            
            if len(device_cusum_data_for_chart) < 2:
                st.warning("Dados insuficientes para o dispositivo selecionado para gerar o gráfico CUSUM.")
            else:
                st.markdown("**Parâmetros do CUSUM:**")
                min_date_cusum = device_cusum_data_for_chart['event_time'].min().date()
                max_date_cusum = device_cusum_data_for_chart['event_time'].max().date()

                ref_start_date = st.date_input("Data Inicial de Referência (para μ, σ):", 
                                               value=min_date_cusum, 
                                               min_value=min_date_cusum, max_value=max_date_cusum, key="cusum_ref_start_avancada")
                ref_end_date = st.date_input("Data Final de Referência (para μ, σ):", 
                                             value=min_date_cusum + timedelta(days=min(6, (max_date_cusum - min_date_cusum).days)), # Use timedelta
                                             min_value=min_date_cusum, max_value=max_date_cusum, key="cusum_ref_end_avancada")
                
                ref_data = device_cusum_data_for_chart[
                    (device_cusum_data_for_chart['event_time'].dt.date >= ref_start_date) &
                    (device_cusum_data_for_chart['event_time'].dt.date <= ref_end_date)
                ]['power_W']

                if not ref_data.empty and len(ref_data) > 1:
                    mu = ref_data.mean()
                    sigma_residuals = ref_data.std() 
                    st.write(f"Média de Referência (μ): {mu:.2f} W")
                    st.write(f"Desvio Padrão de Referência (σ_res): {sigma_residuals:.2f} W")

                    default_nu = (0.5 * sigma_residuals)**2 if sigma_residuals > 0 else 1.0
                    default_h = (5 * sigma_residuals)**2 if sigma_residuals > 0 else 25.0
                    default_nu = max(default_nu, 0.01)
                    default_h = max(default_h, 0.1)

                    param_col1, param_col2 = st.columns(2)
                    nu_cusum = param_col1.number_input("Parâmetro ν (allowance para s_j,i):", 
                                                       min_value=0.0, value=default_nu, step=max(0.01, default_nu/10), format="%.2f", key="cusum_nu_avancada")
                    h_cusum = param_col2.number_input("Limite h (threshold para g_j,i):", 
                                                      min_value=0.0, value=default_h, step=max(0.1, default_h/10), format="%.2f", key="cusum_h_avancada")
                    
                    residuals = device_cusum_data_for_chart['power_W'] - mu
                    s_ji = residuals**2
                    g_ji = np.zeros(len(s_ji))
                    alarms = np.zeros(len(s_ji), dtype=bool)

                    if len(s_ji) > 0:
                        g_ji[0] = max(0, s_ji.iloc[0] - nu_cusum)
                        if g_ji[0] > h_cusum: alarms[0] = True
                    for t in range(1, len(s_ji)):
                        g_ji[t] = max(0, g_ji[t-1] + s_ji.iloc[t] - nu_cusum)
                        if g_ji[t] > h_cusum: alarms[t] = True
                    
                    device_cusum_data_for_chart['cusum_g'] = g_ji
                    device_cusum_data_for_chart['alarm'] = alarms
                    
                    fig_cusum = go.Figure() 
                    fig_cusum.add_trace(go.Scatter(x=device_cusum_data_for_chart['event_time'], y=device_cusum_data_for_chart['cusum_g'],
                                                   mode='lines', name='CUSUM (g_j,i)'))
                    fig_cusum.add_hline(y=h_cusum, line_dash="dash", line_color="red", name=f"Limite h = {h_cusum:.2f}")
                    alarm_points = device_cusum_data_for_chart[device_cusum_data_for_chart['alarm']]
                    fig_cusum.add_trace(go.Scatter(x=alarm_points['event_time'], y=alarm_points['cusum_g'],
                                                   mode='markers', name='Alarme', marker=dict(color='red', size=8)))
                    fig_cusum.update_layout(title=f"Gráfico CUSUM para {cusum_device}",
                                            xaxis_title="Tempo", yaxis_title="Estatística CUSUM (g_j,i)")
                    st.plotly_chart(fig_cusum, use_container_width=True)
                elif not ref_data.empty and len(ref_data) <=1:
                    st.warning("Período de referência muito curto para calcular σ (precisa de >1 ponto).")
                else:
                    st.warning("Nenhum dado no período de referência selecionado para calcular μ e σ.")
        
        st.markdown("---")
        if 'fault' in data_df.columns and not data_df[data_df['fault'].notna()].empty:
            st.subheader("Registros de Falha")
            fault_display_data_avancada = data_df # Use a different variable name to avoid conflict if needed
            if cusum_device: 
                fault_display_data_avancada = data_df[data_df['device_name'] == cusum_device]
            
            fault_data_filtered = fault_display_data_avancada[fault_display_data_avancada['fault'].notna()][['event_time', 'device_name', 'fault']].copy()
            if not fault_data_filtered.empty:
                fault_data_filtered['fault_description'] = fault_data_filtered['fault'].apply(lambda x: x if isinstance(x, str) else str(x)) 
                st.dataframe(fault_data_filtered)
            else:
                st.info(f"Nenhum registro de falha encontrado para {cusum_device if cusum_device else 'os dispositivos selecionados'} no período selecionado.")
        else:
            st.info("Nenhum registro de falha encontrado no período selecionado para os dispositivos filtrados.")
            
    elif not selected_devices_list:
        st.info("Por favor, selecione um dispositivo na barra lateral para ver a Análise Avançada.")
    else: 
        st.info("Carregue os dados e selecione dispositivos para ver a Análise Avançada.")


# --- Streamlit App UI ---
st.set_page_config(layout="wide", page_title="Análise de Energia Residencial")

def local_css(file_name):
    try:
        with open(file_name) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.error(f"CSS file not found: {file_name}. Make sure 'style.css' is in the same directory as the app.")

# Load custom CSS
local_css("style.css") # style.css is in the same directory as this script

st.title("Análise de Consumo de Energia Residencial")

# --- Sidebar ---
st.sidebar.header("Navegação")
app_page = st.sidebar.radio(
    "Selecione uma Página",
    ["🏠 Resumo da Casa", "🔌 Detalhes por Dispositivo", "📊 Análise Avançada"]
)

st.sidebar.header("Filtros Gerais")

today = datetime.now().date()
default_period_options = {
    "Hoje": (today, today),
    "Ontem": (today - timedelta(days=1), today - timedelta(days=1)),
    "Últimos 7 Dias": (today - timedelta(days=6), today),
    "Este Mês": (today.replace(day=1), today),
    "Mês Anterior": ((today.replace(day=1) - timedelta(days=1)).replace(day=1), today.replace(day=1) - timedelta(days=1)),
    "Período Customizado": None 
}
selected_period_label = st.sidebar.selectbox(
    "Selecione o Período:",
    options=list(default_period_options.keys()),
    index=2 
)

if selected_period_label == "Período Customizado":
    default_end_date_custom = today
    default_start_date_custom = default_end_date_custom - timedelta(days=6)
    start_date_filter = st.sidebar.date_input("Data Inicial Customizada", value=default_start_date_custom, key="custom_start_date")
    end_date_filter = st.sidebar.date_input("Data Final Customizada", value=default_end_date_custom, key="custom_end_date")
else:
    start_date_filter, end_date_filter = default_period_options[selected_period_label]

available_devices_list = []
if start_date_filter and end_date_filter and start_date_filter <= end_date_filter:
    available_devices_list = get_available_devices(start_date_filter, end_date_filter)
else:
    st.sidebar.warning("Datas inválidas. Data inicial deve ser anterior ou igual à data final.")

selected_devices_list = []
if available_devices_list:
    selected_devices_list = st.sidebar.multiselect(
        "Filtrar Dispositivos (Global)",
        options=available_devices_list,
        default=available_devices_list 
    )
    if not selected_devices_list: 
         st.sidebar.warning("Selecione ao menos um dispositivo para carregar os dados.")
else:
    st.sidebar.info("Nenhum dispositivo encontrado para o período selecionado ou dados não disponíveis.")

data_df = pd.DataFrame()
if start_date_filter and end_date_filter and start_date_filter <= end_date_filter and selected_devices_list:
    data_df = load_data(start_date_filter, end_date_filter, selected_devices_list) 
elif not selected_devices_list and available_devices_list: 
    st.sidebar.info("Selecione dispositivos no filtro global para carregar dados.")
elif not available_devices_list:
    pass 

if app_page == "🏠 Resumo da Casa": # Match emoji
    show_resumo_casa(data_df, selected_devices_list, start_date_filter, end_date_filter)
elif app_page == "🔌 Detalhes por Dispositivo": # Match emoji
    selected_device_for_detail = None
    if available_devices_list: 
        default_device_for_detail = selected_devices_list[0] if len(selected_devices_list) == 1 else None
        if not available_devices_list and default_device_for_detail: 
             default_device_for_detail = None

        selected_device_for_detail = st.sidebar.selectbox(
            "Selecione um Dispositivo para Detalhes:",
            options=available_devices_list,
            index=available_devices_list.index(default_device_for_detail) if default_device_for_detail and default_device_for_detail in available_devices_list else 0
        )
    show_detalhes_dispositivo(data_df, selected_device_for_detail, start_date_filter, end_date_filter)
elif app_page == "📊 Análise Avançada": # Match emoji
    show_analise_avancada(data_df, selected_devices_list, start_date_filter, end_date_filter)

st.sidebar.markdown("---")
st.sidebar.caption("Desenvolvido por Igor Cleto.")
