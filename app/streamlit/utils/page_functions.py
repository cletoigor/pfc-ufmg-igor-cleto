import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np

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
    
    st.markdown("---") 

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
    
    st.subheader(f"Principais Consumidores ({start_date_filter.strftime('%d/%m')} a {end_date_filter.strftime('%d/%m')})", help="Lista os 5 principais dispositivos por consumo de energia (kWh) no período selecionado.")
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
    
    st.markdown("---") 

    if 'power_W' in data_df.columns:
        st.subheader("Análise de Potência Consolidada (W)", help="Métricas de potência agregada para todos os dispositivos selecionados no período.")
        
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
            st.subheader(f"Consumo de Energia por Dispositivo ({start_date_filter.strftime('%d/%m')} a {end_date_filter.strftime('%d/%m')})", help="Lista o consumo de energia (kWh) para cada dispositivo selecionado no período.")
            for dev, eng in sorted_devices_by_energy:
                st.markdown(f"**{dev}**: {eng:.3f} kWh")
    else:
        st.info("Dados de potência (power_W) não disponíveis para o resumo.")


def show_detalhes_dispositivo(data_df, selected_device_for_detail, start_date_filter, end_date_filter):
    st.header(f"Detalhes do Dispositivo: {selected_device_for_detail if selected_device_for_detail else 'Nenhum Selecionado'}")
    st.write(f"Exibindo dados de {start_date_filter.strftime('%d/%m/%Y')} a {end_date_filter.strftime('%d/%m/%Y')}")

    if data_df.empty: 
        st.info("Nenhum dado global carregado. Verifique os filtros gerais ou a disponibilidade de dados.")
        return

    if not selected_device_for_detail:
        st.info("Por favor, selecione um dispositivo na barra lateral para ver os detalhes.")
        return

    device_specific_data = data_df[data_df['device_name'] == selected_device_for_detail]

    if device_specific_data.empty:
        st.warning(f"Nenhum dado encontrado para o dispositivo '{selected_device_for_detail}' nos filtros selecionados.")
        return

    st.subheader(f"Resumo de Consumo: {selected_device_for_detail}", help=f"Métricas de consumo de energia para o dispositivo {selected_device_for_detail} em diferentes intervalos de tempo recentes.")
    
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
        st.subheader(f"Métricas de Potência ({start_date_filter.strftime('%d/%m')} a {end_date_filter.strftime('%d/%m')})", help=f"Principais indicadores de potência para {selected_device_for_detail} no período selecionado.")
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
            st.subheader("Série Temporal da Potência (W)", help="Este gráfico mostra a variação da potência (em Watts) do dispositivo ao longo do tempo selecionado.")
            fig_power_ts = px.line(device_specific_data, x='event_time', y='power_W',
                                   labels={'event_time': 'Tempo', 'power_W': 'Potência (W)'},
                                   title=f"Potência de {selected_device_for_detail} ao Longo do Tempo")
            st.plotly_chart(fig_power_ts, use_container_width=True)

            st.markdown("---") 
            st.subheader("Consumo de Energia Diário (kWh)", help=f"Consumo total de energia (kWh) por dia para {selected_device_for_detail} no período selecionado.")
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
            st.subheader("Perfil de Potência Médio por Hora do Dia", help=f"Potência média consumida por {selected_device_for_detail} para cada hora do dia, calculado sobre todo o período selecionado.")
            
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
            st.subheader("Métricas de Tensão", help=f"Principais indicadores de tensão para {selected_device_for_detail} no período selecionado.") 
            avg_voltage = device_specific_data['voltage_V'].mean()
            max_voltage = device_specific_data['voltage_V'].max()
            min_voltage = device_specific_data['voltage_V'].min()
            col_v1, col_v2, col_v3 = st.columns(3)
            col_v1.metric("Tensão Média", f"{avg_voltage:.2f} V")
            col_v2.metric("Tensão Máxima", f"{max_voltage:.2f} V")
            col_v3.metric("Tensão Mínima", f"{min_voltage:.2f} V")

            st.subheader("Série Temporal da Tensão (V)", help="Este gráfico mostra a variação da tensão (em Volts) do dispositivo ao longo do tempo selecionado.")
            fig_voltage_ts = px.line(device_specific_data, x='event_time', y='voltage_V',
                                     labels={'event_time': 'Tempo', 'voltage_V': 'Tensão (V)'},
                                     title=f"Tensão de {selected_device_for_detail} ao Longo do Tempo")
            st.plotly_chart(fig_voltage_ts, use_container_width=True)

            st.subheader("Distribuição da Tensão (V)", help=f"Diagrama de caixa (boxplot) mostrando a distribuição estatística dos valores de tensão para {selected_device_for_detail} no período selecionado.")
            fig_voltage_dist = px.box(device_specific_data, y='voltage_V',
                                      labels={'voltage_V': 'Tensão (V)'},
                                      title=f"Distribuição da Tensão para {selected_device_for_detail}")
            st.plotly_chart(fig_voltage_dist, use_container_width=True)
        else: 
            st.info(f"Dados de tensão (voltage_V) não disponíveis para {selected_device_for_detail}.")

    with st.expander(f"Análise de Corrente (mA) - {selected_device_for_detail}", expanded=False):
        if not device_specific_data.empty and 'current_mA' in device_specific_data.columns and not device_specific_data['current_mA'].dropna().empty:
            st.subheader("Métricas de Corrente", help=f"Principais indicadores de corrente para {selected_device_for_detail} no período selecionado.") 
            avg_current = device_specific_data['current_mA'].mean()
            max_current = device_specific_data['current_mA'].max()
            min_current = device_specific_data['current_mA'].min()
            col_c1, col_c2, col_c3 = st.columns(3)
            col_c1.metric("Corrente Média", f"{avg_current:.2f} mA")
            col_c2.metric("Corrente Máxima", f"{max_current:.2f} mA")
            col_c3.metric("Corrente Mínima", f"{min_current:.2f} mA")

            st.subheader("Série Temporal da Corrente (mA)", help="Este gráfico mostra a variação da corrente (em miliamperes) do dispositivo ao longo do tempo selecionado.")
            fig_current_ts = px.line(device_specific_data, x='event_time', y='current_mA',
                                     labels={'event_time': 'Tempo', 'current_mA': 'Corrente (mA)'},
                                     title=f"Corrente de {selected_device_for_detail} ao Longo do Tempo")
            st.plotly_chart(fig_current_ts, use_container_width=True)

            st.subheader("Distribuição da Corrente (mA)", help=f"Diagrama de caixa (boxplot) mostrando a distribuição estatística dos valores de corrente para {selected_device_for_detail} no período selecionado.")
            fig_current_dist = px.box(device_specific_data, y='current_mA',
                                      labels={'current_mA': 'Corrente (mA)'},
                                      title=f"Distribuição da Corrente para {selected_device_for_detail}")
            st.plotly_chart(fig_current_dist, use_container_width=True)
        else:
            st.info(f"Dados de corrente (current_mA) não disponíveis para {selected_device_for_detail}.")


def generate_2d_statistical_profile_plot(device_df, start_date_filter, end_date_filter):
    """
    Generates a 2D multichannel statistical power profile plot for a selected device.
    Shows historical average, uncertainty bands, and the latest week's profile.
    """
    if device_df.empty or 'power_W' not in device_df.columns or device_df['power_W'].isnull().all():
        return go.Figure()

    device_df['event_time'] = pd.to_datetime(device_df['event_time'])
    device_df = device_df.sort_values(by='event_time')

    hourly_energy_kWh_series = device_df.set_index('event_time')['power_W'].resample('h').mean() / 1000.0
    hourly_energy_kWh_series = hourly_energy_kWh_series.dropna()

    if hourly_energy_kWh_series.empty:
        return go.Figure()

    df_processed = hourly_energy_kWh_series.reset_index()
    df_processed['channel'] = df_processed['event_time'].dt.dayofweek * 24 + df_processed['event_time'].dt.hour
    df_processed['week_id'] = df_processed['event_time'].dt.isocalendar().year.astype(str) + '-' + df_processed['event_time'].dt.isocalendar().week.astype(str)

    if df_processed['week_id'].nunique() < 2:
        st.info("Dados insuficientes para análise estatística (necessário pelo menos 2 semanas de dados: 1 histórica e 1 atual).")
        return go.Figure()

    # Identify the most recent complete week
    last_event_date = df_processed['event_time'].max()
    
    # Find the start of the week for the last_event_date
    # A complete week ends on Sunday (weekday 6). If last_event_date is not a Sunday,
    # the current week is incomplete. We need the week *before* that.
    
    # Get unique weeks sorted
    sorted_unique_weeks = df_processed[['event_time']].copy()
    sorted_unique_weeks['year_week'] = sorted_unique_weeks['event_time'].dt.to_period('W')
    unique_year_weeks_sorted = sorted_unique_weeks['year_week'].unique() # Already sorted due to time sort

    if len(unique_year_weeks_sorted) == 0:
        return go.Figure()

    # Determine the most recent *complete* week
    # A simple way: if the last data point's week has 7 days of data up to its end, it's complete.
    # Or, more robustly, define the "current week" as the week containing the last data point.
    # "Historical" is everything before the start of this "current week".
    
    # Let's define "current week" as the week of the last data point.
    # "Historical" is all weeks *before* this current week.
    
    last_data_point_week_id = df_processed['week_id'].iloc[-1]
    
    current_week_df = df_processed[df_processed['week_id'] == last_data_point_week_id]
    historical_df = df_processed[df_processed['week_id'] != last_data_point_week_id]

    if historical_df.empty:
        st.info("Não há dados históricos suficientes (pelo menos uma semana completa antes da semana atual) para calcular o perfil médio.")
        return go.Figure()

    # Calculate historical EWMA and std dev per channel
    alpha = 0.18 # Smoothing factor for EWMA (e.g., equivalent to ~10 past weeks)
    historical_avg_ewma_kwh = pd.Series([0.0] * 168, index=range(168))
    
    # Group historical data by week_id and then by channel to calculate EWMA iteratively
    # This requires processing weeks chronologically for each channel.
    
    # First, ensure historical_df is sorted correctly for EWMA calculation
    historical_df_sorted = historical_df.sort_values(by=['week_id', 'channel'])
    
    # Initialize EWMA for each channel with the first available value for that channel
    # then update with subsequent values.
    # A simpler approach for on-the-fly calculation without persistent state:
    # Calculate EWMA across all historical points for each channel.
    # Pandas ewm().mean() can do this if we group by channel and apply it to the time series of that channel.
    
    # For EWMA per channel based on weekly values:
    # 1. Pivot historical_df to have weeks as index, channels as columns
    if not historical_df_sorted.empty:
        historical_pivot = historical_df_sorted.pivot_table(index='week_id', columns='channel', values='power_W')
        # Ensure all channels 0-167 are present, fill missing with NaN for EWMA to handle
        historical_pivot = historical_pivot.reindex(columns=range(168)) 
        
        # Calculate EWMA for each channel (column)
        # Adjust_false means the weights are not re-normalized at each step, matching the formula's intent.
        ewma_per_channel = historical_pivot.ewm(alpha=alpha, adjust=False).mean()
        
        if not ewma_per_channel.empty:
            # The last row of ewma_per_channel contains the final EWMA values for each channel
            historical_avg_ewma_kwh = ewma_per_channel.iloc[-1].fillna(0.0) # Use last EWMA value
        else: # Fallback if EWMA calculation results in empty (e.g. single week of historical data)
            temp_avg = historical_df_sorted.groupby('channel')['power_W'].mean().reindex(range(168), fill_value=0.0)
            historical_avg_ewma_kwh = temp_avg
    else: # Should not happen due to earlier check, but as a safeguard
        historical_avg_ewma_kwh = pd.Series([0.0] * 168, index=range(168))

    # Standard deviation is still calculated on the raw historical values for simplicity for the bands
    historical_std_dev_kwh = historical_df.groupby('channel')['power_W'].std().reindex(range(168), fill_value=0.0)
    
    historical_stats = pd.DataFrame({
        'channel': range(168),
        'avg_kWh': historical_avg_ewma_kwh.values,
        'std_kWh': historical_std_dev_kwh.values
    })
    historical_stats['std_kWh'].fillna(0, inplace=True)


    # Prepare current week's profile
    current_week_profile = pd.Series([np.nan] * 168, index=range(168))
    for _, row in current_week_df.iterrows():
        current_week_profile[int(row['channel'])] = row['power_W']
    
    # Ensure all channels 0-167 are present in historical_stats, filling missing with NaN or 0
    full_channel_range = pd.DataFrame({'channel': range(168)})
    historical_stats = pd.merge(full_channel_range, historical_stats, on='channel', how='left')
    historical_stats['avg_kWh'].fillna(0, inplace=True) # Or np.nan if you prefer gaps
    historical_stats['std_kWh'].fillna(0, inplace=True) # Or np.nan

    # Create the 2D plot
    fig = go.Figure()
    channels_x = list(range(168))

    # Add historical average
    fig.add_trace(go.Scatter(
        x=channels_x, y=historical_stats['avg_kWh'],
        mode='lines', name='Média Histórica (kWh)',
        line=dict(color='blue')
    ))

    # Add uncertainty bands (+/- 1 std dev)
    fig.add_trace(go.Scatter(
        x=channels_x, y=historical_stats['avg_kWh'] + historical_stats['std_kWh'],
        mode='lines', name='+1 Desvio Padrão',
        line=dict(width=0),
        showlegend=False
    ))
    fig.add_trace(go.Scatter(
        x=channels_x, y=historical_stats['avg_kWh'] - historical_stats['std_kWh'],
        mode='lines', name='-1 Desvio Padrão',
        line=dict(width=0),
        fillcolor='rgba(0,100,80,0.2)',
        fill='tonexty', # Fill area between this trace and the one above
        showlegend=False
    ))
    
    # Add current week's profile
    # Only plot if there's actual data for the current week profile
    if not current_week_profile.isnull().all():
        fig.add_trace(go.Scatter(
            x=channels_x, y=current_week_profile,
            mode='lines', name=f'Semana Atual ({last_data_point_week_id})',
            line=dict(color='red', dash='dash')
        ))

    day_names_short = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    tick_positions = [i * 24 for i in range(7)]
    tick_labels = [day_names_short[i] for i in range(7)]

    fig.update_layout(
        title=f"Perfil Estatístico Multicanal de Energia (kWh por Hora da Semana)",
        xaxis_title='Hora da Semana (Canal)',
        yaxis_title='Energia Consumida (kWh)',
        xaxis=dict(tickmode='array', tickvals=tick_positions, ticktext=tick_labels),
        legend_title_text='Legenda',
        margin=dict(l=0, r=0, b=0, t=50)
    )
    # The function now returns only the figure, as was_truncated is not directly applicable to this 2D plot logic
    return fig


def generate_3d_multichannel_profiles_plot(device_df, start_date_filter, end_date_filter):
    """
    Generates a 3D multichannel power profile plot for a selected device.
    Shows the historical average profile and up to 4 most recent individual weekly profiles.
    """
    if device_df.empty or 'power_W' not in device_df.columns or device_df['power_W'].isnull().all():
        return go.Figure(), False # Figure and a flag indicating if historical average was plotted

    device_df['event_time'] = pd.to_datetime(device_df['event_time'])
    device_df = device_df.sort_values(by='event_time')

    hourly_energy_kWh_series = device_df.set_index('event_time')['power_W'].resample('h').mean() / 1000.0
    hourly_energy_kWh_series = hourly_energy_kWh_series.dropna()

    if hourly_energy_kWh_series.empty:
        return go.Figure(), False

    df_processed = hourly_energy_kWh_series.reset_index()
    df_processed['channel'] = df_processed['event_time'].dt.dayofweek * 24 + df_processed['event_time'].dt.hour
    df_processed['week_id'] = df_processed['event_time'].dt.isocalendar().year.astype(str) + '-' + df_processed['event_time'].dt.isocalendar().week.astype(str)

    if df_processed['week_id'].nunique() == 0: # Need at least one week of data
        return go.Figure(), False

    # --- Calculate Historical Average Profile (EWMA) for 3D plot ---
    historical_avg_profile_kWh_3d = pd.Series([0.0] * 168, index=range(168))
    historical_data_available_3d = False # Renamed to avoid conflict
    alpha_3d = 0.18 # Same alpha, or could be different if desired

    if not df_processed.empty: # Use all data for this EWMA for the 3D plot's baseline
        df_processed_sorted_for_3d_ewma = df_processed.sort_values(by=['week_id', 'channel'])
        pivot_for_3d_ewma = df_processed_sorted_for_3d_ewma.pivot_table(index='week_id', columns='channel', values='power_W')
        pivot_for_3d_ewma = pivot_for_3d_ewma.reindex(columns=range(168))
        
        ewma_3d_per_channel = pivot_for_3d_ewma.ewm(alpha=alpha_3d, adjust=False).mean()
        if not ewma_3d_per_channel.empty:
            historical_avg_profile_kWh_3d = ewma_3d_per_channel.iloc[-1].fillna(0.0)
            historical_data_available_3d = True
        else: # Fallback
            temp_avg_3d = df_processed_sorted_for_3d_ewma.groupby('channel')['power_W'].mean().reindex(range(168), fill_value=0.0)
            historical_avg_profile_kWh_3d = temp_avg_3d
            if not temp_avg_3d.empty: historical_data_available_3d = True


    # --- Prepare Individual Recent Weekly Profiles ---
    plot_data_3d = []
    unique_weeks_sorted = df_processed[['week_id', 'event_time']].copy()
    unique_weeks_sorted['year_week_dt'] = unique_weeks_sorted['event_time'].dt.to_period('W')
    actual_unique_weeks = unique_weeks_sorted['week_id'].unique() # These are sorted by virtue of df_processed being sorted

    # Select up to the last 4 individual weeks
    num_recent_weeks_to_plot = min(len(actual_unique_weeks), 4)
    weeks_to_plot_ids = actual_unique_weeks[-num_recent_weeks_to_plot:]
    
    week_plot_index_counter = 1 # For Y-axis positioning in 3D

    # Add historical average as the first trace (Y=0 or a distinct value)
    if historical_data_available_3d:
        plot_data_3d.append({
            'week_label': "Média Histórica (EWMA)", # Clarified label
            'week_index_for_plot': 0, 
            'channels': historical_avg_profile_kWh_3d.tolist(),
            'line_style': dict(color='rgba(0,0,255,0.7)', width=3, dash='solid') 
        })

    # Iterate through the selected recent weeks for individual plotting
    for i, week_id_val in enumerate(weeks_to_plot_ids):
        current_week_df = df_processed[df_processed['week_id'] == week_id_val]
        week_profile_kWh = pd.Series([0.0] * 168, index=range(168))
        for _, row in current_week_df.iterrows():
            week_profile_kWh[int(row['channel'])] = row['power_W']
        
        plot_data_3d.append({
            'week_label': f"Semana {i + 1}", # Simple week number for legend
            'week_index_for_plot': week_plot_index_counter, # This is the Y-axis position
            'channels': week_profile_kWh.tolist(),
            'line_style': dict(width=2) 
        })
        week_plot_index_counter += 1
        
    if not plot_data_3d:
        return go.Figure(), historical_data_available_3d

    fig3d = go.Figure()
    channels_x_axis = list(range(168))

    all_z_values_3d = [val for week in plot_data_3d for val in week['channels'] if val is not None and not np.isnan(val)]
    z_min_3d = min(all_z_values_3d) if all_z_values_3d else 0
    z_max_3d = max(all_z_values_3d) if all_z_values_3d else 1

    for week_data in plot_data_3d:
        fig3d.add_trace(go.Scatter3d(
            x=channels_x_axis,
            y=[week_data['week_index_for_plot']] * 168,
            z=week_data['channels'],
            mode='lines',
            name=week_data['week_label'],
            line=week_data['line_style']
        ))

    channels_tick_vals_3d = [i * 24 for i in range(7)] + [167]
    channels_tick_text_3d = [str(val) for val in channels_tick_vals_3d]
    
    week_tick_vals_3d = [wd['week_index_for_plot'] for wd in plot_data_3d]
    # Use the simplified week_label for tick text
    week_tick_text_3d = [wd['week_label'] for wd in plot_data_3d]


    fig3d.update_layout(
        title=f"Perfis Semanais 3D e Média Histórica (EWMA, kWh)",
        scene=dict(
            xaxis_title='Canais',
            yaxis_title='Semanas/Média',
            zaxis_title='kWh',
            xaxis=dict(tickvals=channels_tick_vals_3d, ticktext=channels_tick_text_3d),
            yaxis=dict(tickvals=week_tick_vals_3d, ticktext=week_tick_text_3d), # Removed autorange reversed
            zaxis=dict(range=[z_min_3d, z_max_3d]),
            camera=dict(eye=dict(x=1.7, y=-2.0, z=0.7))
        ),
        margin=dict(l=0, r=0, b=0, t=50),
        legend_title_text='Perfis'
    )
    return fig3d, historical_data_available_3d


def show_analise_avancada(data_df, selected_devices_list, start_date_filter, end_date_filter):
    st.header("Análise Avançada")
    st.write(f"Exibindo dados de {start_date_filter.strftime('%d/%m/%Y')} a {end_date_filter.strftime('%d/%m/%Y')}")
    
    if data_df.empty:
        st.info("Nenhum dado disponível para os filtros selecionados.")
        return

    if 'power_W' in data_df.columns:
        st.subheader("Análise de Picos de Potência (Todos Dispositivos Selecionados)", help="Identifica o momento e o valor do pico de potência para cada dispositivo selecionado no período.")
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
    st.subheader("Controle Estatístico de Processo (CEP/SPC)", help="Ferramentas de CEP para monitorar a estabilidade do consumo de energia.")
    if not data_df.empty and 'power_W' in data_df.columns and selected_devices_list:
        st.subheader("Gráfico CUSUM para Detecção de Mudanças na Potência", help="O gráfico CUSUM (Cumulative Sum) é usado para detectar pequenas mas persistentes mudanças na média de um processo. Neste caso, monitora a potência do dispositivo selecionado.")

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
                                             value=min_date_cusum + timedelta(days=min(6, (max_date_cusum - min_date_cusum).days)), 
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
            st.subheader("Registros de Falha", help="Exibe os registros de falha (código 'fault') reportados pelos dispositivos no período selecionado.")
            fault_display_data_avancada = data_df 
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
