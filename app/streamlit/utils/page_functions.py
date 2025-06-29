import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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
    
    st.subheader(f"Principais Consumidores ({start_date_filter.strftime('%d/%m')} a {end_date_filter.strftime('%d/%m')})", help="Lista os 3 principais dispositivos por consumo de energia (kWh) no período selecionado.")
    if current_device_energy_global_period:
        sorted_top_consumers = sorted(current_device_energy_global_period.items(), key=lambda item: item[1], reverse=True)
        
        num_to_display = min(len(sorted_top_consumers), 3) 
        if num_to_display > 0:
            top_consumers_df = pd.DataFrame(sorted_top_consumers[:num_to_display], columns=['Dispositivo', 'Consumo (kWh)'])
            
            trophy_emojis = ["🥇", "🥈", "🥉"]
            top_consumers_df_display = top_consumers_df.copy()
            for i in range(min(len(top_consumers_df_display), 3)): 
                top_consumers_df_display.loc[i, 'Dispositivo'] = f"{trophy_emojis[i]} {top_consumers_df_display.loc[i, 'Dispositivo']}"

            st.markdown("##### Pódio dos Consumidores:")
            for index, row in top_consumers_df_display.iterrows():
                st.markdown(f"- {row['Dispositivo']}: {row['Consumo (kWh)']:.2f} kWh")

            if not top_consumers_df_display.empty:
                fig_top_consumers_bar = px.bar(top_consumers_df_display, 
                                               y='Dispositivo', 
                                               x='Consumo (kWh)',
                                               orientation='h',
                                               title="Top 3 Consumidores de Energia",
                                               labels={'Consumo (kWh)': 'Energia Consumida (kWh)', 'Dispositivo': 'Dispositivo'},
                                               text='Consumo (kWh)')
                fig_top_consumers_bar.update_traces(texttemplate='%{text:.2f} kWh', textposition='outside')
                fig_top_consumers_bar.update_layout(yaxis={'categoryorder':'total ascending'},
                                                    xaxis_title="Energia Consumida (kWh)",
                                                    yaxis_title="Dispositivo")
                st.plotly_chart(fig_top_consumers_bar, use_container_width=True)
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

        st.markdown("---")
        st.subheader("Perfil Médio de Consumo Horário (Todos Dispositivos)", help="Potência média consumida por todos os dispositivos selecionados para cada hora do dia, calculado sobre o período selecionado.")
        if not data_df.empty and 'power_W' in data_df.columns and not data_df['power_W'].dropna().empty:
            data_df_copy = data_df.copy()
            data_df_copy['hour_of_day'] = data_df_copy['event_time'].dt.hour
            hourly_avg_power_all_devices = data_df_copy.groupby('hour_of_day')['power_W'].mean().reset_index()
            
            if not hourly_avg_power_all_devices.empty:
                fig_hourly_avg_all = px.line(hourly_avg_power_all_devices, x='hour_of_day', y='power_W',
                                             labels={'hour_of_day': 'Hora do Dia', 'power_W': 'Potência Média Consolidada (W)'},
                                             title="Perfil Médio de Potência Horária (Todos Dispositivos)",
                                             markers=True)
                fig_hourly_avg_all.update_xaxes(tickvals=list(range(24)), dtick=2)
                st.plotly_chart(fig_hourly_avg_all, use_container_width=True)
            else:
                st.info("Não há dados suficientes para exibir o perfil de potência horária consolidado.")
        else:
            st.info("Dados de potência (power_W) não disponíveis para o perfil horário.")

        st.markdown("---")
        st.subheader("Distribuição do Consumo por Dispositivo", help="Contribuição de cada dispositivo para o consumo total de energia (kWh) no período selecionado.")
        if current_device_energy_global_period:
            positive_energy_consumers = {dev: eng for dev, eng in current_device_energy_global_period.items() if eng > 0.001}
            if positive_energy_consumers:
                bar_df = pd.DataFrame(list(positive_energy_consumers.items()), columns=['Dispositivo', 'Consumo (kWh)'])
                bar_df = bar_df.sort_values(by='Consumo (kWh)', ascending=False) 
                
                fig_bar_consumers = px.bar(bar_df, y='Dispositivo', x='Consumo (kWh)', 
                                           orientation='h',
                                           title="Consumo de Energia por Dispositivo",
                                           labels={'Consumo (kWh)': 'Energia Consumida (kWh)', 'Dispositivo': 'Dispositivo'},
                                           text='Consumo (kWh)') 
                fig_bar_consumers.update_traces(texttemplate='%{text:.2f} kWh', textposition='outside')
                fig_bar_consumers.update_layout(yaxis={'categoryorder':'total ascending'}) 
                st.plotly_chart(fig_bar_consumers, use_container_width=True)
            else:
                st.info("Nenhum dispositivo com consumo significativo para exibir no gráfico de barras.")
        else:
            st.info("Cálculo de consumo por dispositivo não disponível para o gráfico de barras.")
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
            
            fig_power_ts = go.Figure()
            fig_power_ts.add_trace(go.Scatter(
                x=device_specific_data['event_time'], 
                y=device_specific_data['power_W'],
                mode='lines', name='Potência (W)', line=dict(color='rgb(255,165,0)') # Orange
            ))
            fig_power_ts.update_layout(
                title=f"Potência de {selected_device_for_detail} ao Longo do Tempo",
                xaxis_title='Tempo', yaxis_title='Potência (W)'
            )
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
            
            fig_voltage_ts = go.Figure()
            fig_voltage_ts.add_trace(go.Scatter(
                x=device_specific_data['event_time'],
                y=device_specific_data['voltage_V'],
                mode='lines', name='Tensão (V)', line=dict(color='rgb(0,128,0)') # Green
            ))
            fig_voltage_ts.update_layout(
                title=f"Tensão de {selected_device_for_detail} ao Longo do Tempo",
                xaxis_title='Tempo', yaxis_title='Tensão (V)'
            )
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
            
            fig_current_ts = go.Figure()
            fig_current_ts.add_trace(go.Scatter(
                x=device_specific_data['event_time'],
                y=device_specific_data['current_mA'],
                mode='lines', name='Corrente (mA)', line=dict(color='rgb(128,0,128)') # Purple
            ))
            fig_current_ts.update_layout(
                title=f"Corrente de {selected_device_for_detail} ao Longo do Tempo",
                xaxis_title='Tempo', yaxis_title='Corrente (mA)'
            )
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
    Shows historical average (EWMA), uncertainty bands (std dev), and the latest week's profile.
    Also generates a plot with daily average profiles for each day of the week.
    """
    if device_df.empty or 'power_W' not in device_df.columns or device_df['power_W'].isnull().all():
        return go.Figure(), go.Figure() # Return two empty figures if no data

    device_df['event_time'] = pd.to_datetime(device_df['event_time'])
    device_df = device_df.sort_values(by='event_time')

    hourly_energy_kWh_series = device_df.set_index('event_time')['power_W'].resample('h').mean() / 1000.0
    hourly_energy_kWh_series = hourly_energy_kWh_series.dropna()

    if hourly_energy_kWh_series.empty:
        return go.Figure(), go.Figure()

    df_processed = hourly_energy_kWh_series.reset_index()
    df_processed['channel'] = df_processed['event_time'].dt.dayofweek * 24 + df_processed['event_time'].dt.hour
    df_processed['day_of_week_num'] = df_processed['event_time'].dt.dayofweek # Monday=0, Sunday=6
    df_processed['hour_of_day'] = df_processed['event_time'].dt.hour
    df_processed['year_week_id'] = df_processed['event_time'].dt.strftime('%Y-%U') 

    day_names_map = {0: 'Segunda', 1: 'Terça', 2: 'Quarta', 3: 'Quinta', 4: 'Sexta', 5: 'Sábado', 6: 'Domingo'}
    df_processed['day_name'] = df_processed['day_of_week_num'].map(day_names_map)
    
    daily_avg_power = df_processed.groupby(['day_name', 'day_of_week_num', 'hour_of_day'])['power_W'].mean().reset_index()
    daily_avg_power = daily_avg_power.sort_values(by=['day_of_week_num', 'hour_of_day'])

    fig_daily_profiles = make_subplots(
        rows=4, cols=2, 
        subplot_titles=[day_names_map[i] for i in range(7)] + [" "], 
        vertical_spacing=0.15, 
        shared_xaxes=False 
    )

    day_plot_positions = [(1,1), (1,2), (2,1), (2,2), (3,1), (3,2), (4,1)] 

    for i in range(7): 
        day_data = daily_avg_power[daily_avg_power['day_of_week_num'] == i]
        row_idx, col_idx = day_plot_positions[i]
        
        show_xaxis_title = False
        if row_idx == 4: 
             show_xaxis_title = True
        elif row_idx == 3 and col_idx == 2: 
             show_xaxis_title = True

        if not day_data.empty:
            fig_daily_profiles.add_trace(
                go.Scatter(x=day_data['hour_of_day'], y=day_data['power_W'], mode='lines', name=day_names_map[i], showlegend=False), 
                row=row_idx, col=col_idx
            )
            fig_daily_profiles.update_xaxes(
                tickvals=list(range(0, 24, 5)), 
                title_text="Hora" if show_xaxis_title else "", 
                row=row_idx, col=col_idx
            )
            fig_daily_profiles.update_yaxes(title_text="Potência (kW)", row=row_idx, col=col_idx) 
    
    fig_daily_profiles.update_layout(
        height=1000, 
        title_text="Perfis Médios Diários de Consumo (kW)", 
        showlegend=False,
        margin=dict(t=60, b=50, l=50, r=30) 
    )

    if df_processed['year_week_id'].nunique() < 2:
        st.info("Dados insuficientes para análise estatística semanal (necessário pelo menos 2 semanas de dados: 1 histórica e 1 atual).")
        return go.Figure(), fig_daily_profiles if not daily_avg_power.empty else go.Figure()
    
    unique_sorted_weeks = sorted(df_processed['year_week_id'].unique())
    last_full_week_id = unique_sorted_weeks[-1] 
    
    current_week_df = df_processed[df_processed['year_week_id'] == last_full_week_id]
    historical_df = df_processed[df_processed['year_week_id'] < last_full_week_id] 

    if historical_df.empty:
        st.info("Não há dados históricos suficientes (pelo menos uma semana completa antes da semana atual) para calcular o perfil médio semanal.")
        return go.Figure(), fig_daily_profiles if not daily_avg_power.empty else go.Figure()

    alpha = 0.18 
    
    historical_pivot = historical_df.pivot_table(index='year_week_id', columns='channel', values='power_W')
    historical_pivot = historical_pivot.reindex(columns=range(168)) 
    
    ewma_per_channel = historical_pivot.ewm(alpha=alpha, adjust=False, min_periods=1).mean()
    
    historical_avg_ewma_kwh = pd.Series([0.0] * 168, index=range(168))
    if not ewma_per_channel.empty:
        historical_avg_ewma_kwh = ewma_per_channel.iloc[-1].fillna(0.0) 
    else: 
        temp_avg = historical_df.groupby('channel')['power_W'].mean().reindex(range(168), fill_value=0.0)
        historical_avg_ewma_kwh = temp_avg

    historical_std_dev_kwh = historical_df.groupby('channel')['power_W'].std().reindex(range(168), fill_value=0.0)
    
    historical_stats = pd.DataFrame({
        'channel': range(168),
        'avg_kWh': historical_avg_ewma_kwh.values, 
        'std_kWh': historical_std_dev_kwh.values
    })
    historical_stats['std_kWh'].fillna(0, inplace=True) 

    current_week_profile = pd.Series([np.nan] * 168, index=range(168))
    for _, row in current_week_df.iterrows():
        current_week_profile[int(row['channel'])] = row['power_W']
    
    full_channel_range = pd.DataFrame({'channel': range(168)})
    historical_stats = pd.merge(full_channel_range, historical_stats, on='channel', how='left')
    historical_stats['avg_kWh'].fillna(0, inplace=True) 
    historical_stats['std_kWh'].fillna(0, inplace=True) 

    fig = go.Figure()
    channels_x = list(range(168))

    fig.add_trace(go.Scatter(
        x=channels_x, y=historical_stats['avg_kWh'],
        mode='lines', name='Média Histórica (kWh)',
        line=dict(color='blue')
    ))

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
        fill='tonexty', 
        showlegend=False
    ))
    
    if not current_week_profile.isnull().all():
        fig.add_trace(go.Scatter(
            x=channels_x, y=current_week_profile,
            mode='lines', name=f'Semana Atual ({last_full_week_id})',
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
    return fig, fig_daily_profiles if not daily_avg_power.empty else go.Figure()


def generate_3d_multichannel_profiles_plot(device_df, start_date_filter, end_date_filter):
    if device_df.empty or 'power_W' not in device_df.columns or device_df['power_W'].isnull().all():
        return go.Figure(), False 

    device_df['event_time'] = pd.to_datetime(device_df['event_time'])
    device_df = device_df.sort_values(by='event_time')

    hourly_energy_kWh_series = device_df.set_index('event_time')['power_W'].resample('h').mean() / 1000.0
    hourly_energy_kWh_series = hourly_energy_kWh_series.dropna()

    if hourly_energy_kWh_series.empty:
        return go.Figure(), False

    df_processed = hourly_energy_kWh_series.reset_index()
    df_processed['channel'] = df_processed['event_time'].dt.dayofweek * 24 + df_processed['event_time'].dt.hour
    df_processed['year_week_id'] = df_processed['event_time'].dt.strftime('%Y-%U')
    df_processed['week_id'] = df_processed['year_week_id'] 

    if df_processed['week_id'].nunique() == 0: 
        return go.Figure(), False

    historical_avg_profile_kWh_3d = pd.Series([0.0] * 168, index=range(168))
    historical_data_available_3d = False
    alpha_3d = 0.18 

    if not df_processed.empty:
        pivot_all_data_for_3d_ewma = df_processed.pivot_table(index='year_week_id', columns='channel', values='power_W')
        pivot_all_data_for_3d_ewma = pivot_all_data_for_3d_ewma.reindex(columns=range(168))
        
        ewma_all_data_3d = pivot_all_data_for_3d_ewma.ewm(alpha=alpha_3d, adjust=False, min_periods=1).mean()
        if not ewma_all_data_3d.empty:
            historical_avg_profile_kWh_3d = ewma_all_data_3d.iloc[-1].fillna(0.0)
            historical_data_available_3d = True
        else: 
            temp_avg_3d = df_processed.groupby('channel')['power_W'].mean().reindex(range(168), fill_value=0.0)
            historical_avg_profile_kWh_3d = temp_avg_3d
            if not temp_avg_3d.empty: historical_data_available_3d = True
            
    plot_data_3d = []
    actual_unique_weeks_for_3d = sorted(df_processed['year_week_id'].unique())

    num_recent_weeks_to_plot = min(len(actual_unique_weeks_for_3d), 4)
    weeks_to_plot_ids_3d = actual_unique_weeks_for_3d[-num_recent_weeks_to_plot:]
    
    week_plot_index_counter = 1 

    if historical_data_available_3d:
        plot_data_3d.append({
            'week_label': "Média Histórica (EWMA)",
            'week_index_for_plot': 0, 
            'channels': historical_avg_profile_kWh_3d.tolist(),
            'line_style': dict(color='rgba(0,0,255,0.7)', width=3, dash='solid') 
        })

    for i, week_id_val_3d in enumerate(weeks_to_plot_ids_3d):
        current_week_data_3d = df_processed[df_processed['year_week_id'] == week_id_val_3d]
        week_profile_kWh_3d = pd.Series([0.0] * 168, index=range(168))
        for _, row_3d in current_week_data_3d.iterrows():
            week_profile_kWh_3d[int(row_3d['channel'])] = row_3d['power_W']
        
        plot_data_3d.append({
            'week_label': f"Semana {i + 1}", 
            'week_index_for_plot': week_plot_index_counter, 
            'channels': week_profile_kWh_3d.tolist(),
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
    week_tick_text_3d = [wd['week_label'] for wd in plot_data_3d]

    fig3d.update_layout(
        title=f"Perfis Semanais 3D e Média Histórica (EWMA, kWh)",
        scene=dict(
            xaxis_title='Canais',
            yaxis_title='Semanas/Média',
            zaxis_title='kWh',
            xaxis=dict(tickvals=channels_tick_vals_3d, ticktext=channels_tick_text_3d),
            yaxis=dict(tickvals=week_tick_vals_3d, ticktext=week_tick_text_3d), 
            zaxis=dict(range=[z_min_3d, z_max_3d]),
            camera=dict(eye=dict(x=1.7, y=-2.0, z=0.7))
        ),
        margin=dict(l=0, r=0, b=0, t=50),
        legend_title_text='Perfis'
    )
    return fig3d, historical_data_available_3d


def generate_2d_overlaid_weekly_profiles_plot(device_df, start_date_filter, end_date_filter):
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
    df_processed['year_week_id'] = df_processed['event_time'].dt.strftime('%Y-%U')

    unique_weeks_sorted = sorted(df_processed['year_week_id'].unique())

    num_recent_weeks_to_plot = min(len(unique_weeks_sorted), 5)
    weeks_to_plot_ids = unique_weeks_sorted[-num_recent_weeks_to_plot:]

    plot_data_2d_overlay = []

    for i, week_id_val in enumerate(weeks_to_plot_ids):
        current_week_df = df_processed[df_processed['year_week_id'] == week_id_val]
        week_profile_kWh = pd.Series([0.0] * 168, index=range(168))
        for _, row in current_week_df.iterrows():
            week_profile_kWh[int(row['channel'])] = row['power_W']

        plot_data_2d_overlay.append({
            'week_label': f"Semana {i + 1}", 
            'channels': week_profile_kWh.tolist()
        })

    if not plot_data_2d_overlay:
        return go.Figure()

    fig2d_overlay = go.Figure()
    channels_x_axis = list(range(168))

    for week_data in plot_data_2d_overlay:
        fig2d_overlay.add_trace(go.Scatter(
            x=channels_x_axis,
            y=week_data['channels'],
            mode='lines',
            name=week_data['week_label']
        ))

    day_names_short = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    tick_positions = [i * 24 for i in range(7)]
    tick_labels = [day_names_short[i] for i in range(7)]

    fig2d_overlay.update_layout(
        title=f"Perfis Semanais Sobrepostos (kWh por Hora da Semana)",
        xaxis_title='Hora da Semana (Canal)',
        yaxis_title='Energia Consumida (kWh)',
        xaxis=dict(tickmode='array', tickvals=tick_positions, ticktext=tick_labels),
        legend_title_text='Semanas',
        margin=dict(l=0, r=0, b=0, t=50)
    )
    return fig2d_overlay


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
        
        if isinstance(start_date_filter, datetime):
            start_date_obj = start_date_filter.date()
        else:
            start_date_obj = start_date_filter

        if isinstance(end_date_filter, datetime):
            end_date_obj = end_date_filter.date()
        else:
            end_date_obj = end_date_filter
            
        period_duration = (end_date_obj - start_date_obj).days

        if period_duration >= 30:
            st.subheader("Análise de Desvio por Canal Horário", help="Este método estatístico compara o consumo de cada hora da semana (canal) da semana mais recente com sua própria média histórica (EWMA), sinalizando desvios significativos.")
            
            st.markdown("""
            **Metodologia:**

            Esta não é uma carta CUSUM tradicional que acumula desvios ao longo do tempo. Em vez disso, é uma **análise de desvio por canal**, onde cada um dos 168 canais horários da semana é avaliado de forma independente.

            1.  **Linha de Base (μ₀):** Para cada canal, calculamos uma média histórica de consumo usando uma Média Móvel Exponencialmente Ponderada (EWMA). Esta é a nossa expectativa de consumo para aquele horário.
            2.  **Valor Atual (Xᵢ):** O consumo real do canal na semana mais recente.
            3.  **Cálculo do Desvio:** Medimos o quão longe o valor atual está da linha de base, considerando uma "folga" (K) para variações normais.
                *   **Desvio para Cima (Aumento):** `D⁺ = max(0, Xᵢ - (μ₀ + K))`
                *   **Desvio para Baixo (Redução):** `D⁻ = max(0, (μ₀ - K) - Xᵢ)`
            4.  **Alarme:** Um alarme é disparado se o desvio (D⁺ ou D⁻) ultrapassar um Limite de Decisão (H).
                *   `K = k * σ₀` (onde `k` é um fator ajustável e `σ₀` é o desvio padrão histórico do canal)
                *   `H = h * σ₀` (onde `h` é um fator ajustável)
            """)

            cusum_device = st.selectbox("Selecione um dispositivo para a Análise de Desvio:", selected_devices_list, key="cusum_multichannel_device")

            if cusum_device:
                device_data_for_cusum = data_df[data_df['device_name'] == cusum_device].copy()
                device_data_for_cusum.sort_values(by='event_time', inplace=True)

                if len(device_data_for_cusum) < 2:
                    st.warning("Dados insuficientes para o dispositivo selecionado para gerar a análise (necessário pelo menos 2 semanas).")
                else:
                    hourly_energy_cusum = device_data_for_cusum.set_index('event_time')['power_W'].resample('h').mean() / 1000.0
                    hourly_energy_cusum = hourly_energy_cusum.dropna().reset_index()
                    hourly_energy_cusum['channel'] = hourly_energy_cusum['event_time'].dt.dayofweek * 24 + hourly_energy_cusum['event_time'].dt.hour
                    hourly_energy_cusum['year_week_id'] = hourly_energy_cusum['event_time'].dt.strftime('%Y-%U')

                    unique_weeks_cusum = sorted(hourly_energy_cusum['year_week_id'].unique())

                    if len(unique_weeks_cusum) < 2:
                        st.warning("A análise requer pelo menos 2 semanas de dados (1 para referência EWMA, 1 para análise).")
                    else:
                        current_week_id_cusum = unique_weeks_cusum[-1]
                        historical_weeks_df_cusum = hourly_energy_cusum[hourly_energy_cusum['year_week_id'] < current_week_id_cusum]
                        current_week_df_cusum = hourly_energy_cusum[hourly_energy_cusum['year_week_id'] == current_week_id_cusum]

                        if historical_weeks_df_cusum.empty:
                            st.warning("Não há semanas históricas suficientes para calcular a média EWMA.")
                        else:
                            alpha_ewma_cusum = 0.18
                            historical_pivot_cusum = historical_weeks_df_cusum.pivot_table(index='year_week_id', columns='channel', values='power_W')
                            historical_pivot_cusum = historical_pivot_cusum.reindex(columns=range(168))
                            ewma_per_channel_cusum = historical_pivot_cusum.ewm(alpha=alpha_ewma_cusum, adjust=False, min_periods=1).mean()
                            
                            mu0 = pd.Series([0.0] * 168, index=range(168))
                            if not ewma_per_channel_cusum.empty:
                                mu0 = ewma_per_channel_cusum.iloc[-1].fillna(0.0)
                            
                            V_vmv_current_week = pd.Series([np.nan] * 168, index=range(168))
                            for _, row in current_week_df_cusum.iterrows():
                                V_vmv_current_week[int(row['channel'])] = row['power_W']
                            
                            sigma0 = historical_weeks_df_cusum.groupby('channel')['power_W'].std().reindex(range(168), fill_value=0.0)
                            sigma0[sigma0 == 0] = np.finfo(float).eps

                            st.markdown("**Parâmetros de Controle:**")
                            param_col1_mc, param_col2_mc = st.columns(2)
                            k_factor = param_col1_mc.number_input("Fator de Folga (k)", min_value=0.0, value=0.5, step=0.1, format="%.2f", key="k_factor_cusum", help="Multiplica o desvio padrão para criar uma 'zona neutra' em torno da média. Aumentar `k` torna o sistema menos sensível a pequenas variações.")
                            h_factor = param_col2_mc.number_input("Fator de Decisão (h)", min_value=0.0, value=5.0, step=0.5, format="%.2f", key="h_factor_cusum", help="Multiplica o desvio padrão para definir o limite de alarme. Aumentar `h` torna o sistema menos propenso a alarmes.")

                            K = k_factor * sigma0
                            H = h_factor * sigma0

                            SHi = (V_vmv_current_week - (mu0 + K)).clip(lower=0)
                            SLi = ((mu0 - K) - V_vmv_current_week).clip(lower=0)
                            
                            deviation_score = SHi - SLi

                            alarms_upper = SHi > H
                            alarms_lower = SLi > H
                            any_alarm = alarms_upper | alarms_lower

                            cusum_results_df = pd.DataFrame({
                                'Canal': range(168),
                                'Média Hist. (μ₀)': mu0,
                                'Valor Semana Atual (Xᵢ)': V_vmv_current_week,
                                'Desvio (D)': deviation_score,
                                'Limite Superior (H)': H,
                                'Limite Inferior (H)': -H,
                                'Alarme': any_alarm
                            })

                            st.write(f"Análise de Desvio para a semana: {current_week_id_cusum}")

                            # --- Gráfico 1: Perfil de Consumo vs. Média Histórica ---
                            st.subheader("Perfil de Consumo da Semana Atual vs. Histórico")
                            fig_profile = go.Figure()
                            
                            # Média Histórica
                            fig_profile.add_trace(go.Scatter(x=cusum_results_df['Canal'], y=cusum_results_df['Média Hist. (μ₀)'], mode='lines', name='Média Histórica (μ₀)', line=dict(color='blue', dash='dot')))
                            

                            # Consumo da Semana Atual
                            fig_profile.add_trace(go.Scatter(x=cusum_results_df['Canal'], y=cusum_results_df['Valor Semana Atual (Xᵢ)'], mode='lines', name='Semana Atual (Xᵢ)', line=dict(color='green')))

                            # Adicionar K e H ao Gráfico 1
                            # K (folga) é aplicado em torno da média (mu0)
                            # H (limite de decisão) é o limite para o desvio acumulado, mas aqui é o limite para o desvio instantâneo
                            # Para plotar K e H no gráfico de perfil, eles precisam ser relativos à média (mu0)
                            fig_profile.add_trace(go.Scatter(x=cusum_results_df['Canal'], y=cusum_results_df['Média Hist. (μ₀)'] + K, mode='lines', name='Limite Superior (μ₀ + K)', line=dict(color='orange', dash='dot')))
                            fig_profile.add_trace(go.Scatter(x=cusum_results_df['Canal'], y=cusum_results_df['Média Hist. (μ₀)'] - K, mode='lines', name='Limite Inferior (μ₀ - K)', line=dict(color='orange', dash='dot')))
                            
                            # Adicionando os limites de alarme H diretamente no gráfico de perfil
                            fig_profile.add_trace(go.Scatter(x=cusum_results_df['Canal'], y=cusum_results_df['Média Hist. (μ₀)'] + H, mode='lines', name='Limite de Alarme Superior (μ₀ + H)', line=dict(color='red', dash='dash')))
                            fig_profile.add_trace(go.Scatter(x=cusum_results_df['Canal'], y=cusum_results_df['Média Hist. (μ₀)'] - H, mode='lines', name='Limite de Alarme Inferior (μ₀ - H)', line=dict(color='red', dash='dash')))


                            # Pontos de Alarme
                            alarm_points = cusum_results_df[cusum_results_df['Alarme']]
                            fig_profile.add_trace(go.Scatter(x=alarm_points['Canal'], y=alarm_points['Valor Semana Atual (Xᵢ)'], mode='markers', name='Alarme', marker=dict(color='red', size=8, symbol='x')))

                            day_names_short = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
                            tick_positions = [i * 24 for i in range(7)]
                            fig_profile.update_layout(height=400, title_text=f"<b>Perfil de Consumo (kWh)</b><br>Dispositivo: {cusum_device}", xaxis_title="Canal (Hora da Semana)", yaxis_title="Consumo (kWh)", xaxis=dict(tickmode='array', tickvals=tick_positions, ticktext=day_names_short))
                            st.plotly_chart(fig_profile, use_container_width=True)


                            # --- Gráfico 2: Gráfico de Desvio ---
                            st.subheader("Carta de Controle de Desvios")
                            fig_deviation = go.Figure()

                            colors = np.where(cusum_results_df['Alarme'], 'red', np.where(cusum_results_df['Desvio (D)'] > 0, 'blue', 'green'))
                            fig_deviation.add_trace(go.Bar(x=cusum_results_df['Canal'], y=cusum_results_df['Desvio (D)'], marker_color=colors, name='Desvio (D)'))
                            
                            fig_deviation.add_trace(go.Scatter(x=cusum_results_df['Canal'], y=cusum_results_df['Limite Superior (H)'], mode='lines', name='Limite de Decisão (H)', line=dict(color='red', dash='dash')))
                            fig_deviation.add_trace(go.Scatter(x=cusum_results_df['Canal'], y=cusum_results_df['Limite Inferior (H)'], mode='lines', name='Limite de Decisão (-H)', line=dict(color='red', dash='dash')))

                            fig_deviation.update_layout(height=400, title_text=f"<b>Carta de Controle de Desvios</b><br>Dispositivo: {cusum_device}", xaxis_title="Canal (Hora da Semana)", yaxis_title="Valor do Desvio", showlegend=True, xaxis=dict(tickmode='array', tickvals=tick_positions, ticktext=day_names_short))
                            st.plotly_chart(fig_deviation, use_container_width=True)

                            st.info("O **Limite de Decisão (H)** no gráfico acima define o limiar para um alarme. Se a barra de desvio cruzar esta linha, o canal é marcado como um alarme, indicando uma variação de consumo estatisticamente significativa.")

                            alarming_channels = cusum_results_df[cusum_results_df['Alarme']]
                            if not alarming_channels.empty:
                                st.write("Canais em Alarme:")
                                st.dataframe(alarming_channels[['Canal', 'Média Hist. (μ₀)', 'Valor Semana Atual (Xᵢ)', 'Desvio (D)', 'Limite Superior (H)']])
                            else:
                                st.write("Nenhum canal em alarme para a semana atual com os parâmetros definidos.")
        else:
            st.info("A análise de desvio por canal requer um período de dados de pelo menos 30 dias. Por favor, ajuste os filtros.")
            
        st.markdown("---")
        if 'fault' in data_df.columns and not data_df[data_df['fault'].notna()].empty:
            st.subheader("Registros de Falha", help="Exibe os registros de falha (código 'fault') reportados pelos dispositivos no período selecionado.")
            fault_display_data_avancada = data_df 
            # Ensure cusum_device is defined if period_duration < 30
            cusum_device_for_fault = st.selectbox("Selecione um dispositivo para filtrar falhas (opcional):", ["Todos"] + selected_devices_list, key="fault_device_selector_avancada")
            if cusum_device_for_fault != "Todos":
                fault_display_data_avancada = data_df[data_df['device_name'] == cusum_device_for_fault]

            fault_data_filtered = fault_display_data_avancada[fault_display_data_avancada['fault'].notna()][['event_time', 'device_name', 'fault']].copy()
            if not fault_data_filtered.empty:
                fault_data_filtered['fault_description'] = fault_data_filtered['fault'].apply(lambda x: x if isinstance(x, str) else str(x)) 
                st.dataframe(fault_data_filtered)
            else:
                st.info(f"Nenhum registro de falha encontrado para '{cusum_device_for_fault if cusum_device_for_fault != 'Todos' else 'os dispositivos selecionados'}' no período selecionado.")
        else:
            st.info("Nenhum registro de falha encontrado no período selecionado para os dispositivos filtrados.")
            
    elif not selected_devices_list:
        st.info("Por favor, selecione um dispositivo na barra lateral para ver a Análise Avançada.")
    else: 
        st.info("Carregue os dados e selecione dispositivos para ver a Análise Avançada.")
