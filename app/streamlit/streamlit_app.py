import streamlit as st
import pandas as pd
import os
import json
from datetime import datetime, timedelta
import numpy as np

# Import refactored functions
from utils.data_helpers import load_data, get_available_devices, parse_cemig_bill, generate_report
from utils.ui_helpers import local_css
from utils.page_functions import show_resumo_casa, show_detalhes_dispositivo, show_analise_avancada, generate_2d_statistical_profile_plot, generate_3d_multichannel_profiles_plot, generate_2d_overlaid_weekly_profiles_plot
from utils.tuya_api_helpers import list_devices, get_device_status, send_device_command, execute_scene

# --- Streamlit App UI ---
st.set_page_config(layout="wide", page_title="Análise de Energia Residencial")

STYLE_CSS_PATH = "style.css"
with open("style.css") as f:
    css = f.read()
st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

st.title("Análise de Consumo de Energia Residencial")

# --- Sidebar ---
st.sidebar.header("Navegação")

# Main menu: Reports or Actions
main_menu = st.sidebar.radio(
    "Selecione o Menu",
    ["📊 Relatórios", "💡 Acionamentos"]
)

# Second level navigation based on main menu selection
app_page = None # Initialize app_page
if main_menu == "📊 Relatórios":
    app_page = st.sidebar.radio(
        "Selecione a Página de Relatório",
        ["🏠 Resumo da Casa", "🔌 Detalhes por Dispositivo", "📊 Análise Avançada", "🧾 Analisar Conta CEMIG"],
        key="report_page_selector" # Added key for uniqueness
    )
elif main_menu == "💡 Acionamentos":
    app_page = st.sidebar.radio(
        "Selecione a Página de Acionamento",
        ["💡 Controle de Dispositivos"],
        key="action_page_selector" # Added key for uniqueness
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
default_period_key = "Últimos 7 Dias"
selected_period_label = st.sidebar.selectbox(
    "Selecione o Período:",
    options=list(default_period_options.keys()),
    index=list(default_period_options.keys()).index(default_period_key)
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
    default_selection = []
    if app_page == "🏠 Resumo da Casa": # app_page is now defined before this block
        default_selection = available_devices_list
    elif app_page and app_page != "💡 Controle de Dispositivos" and app_page != "🧾 Analisar Conta CEMIG": # Check if app_page is not None and not a page that doesn't need this default
        if "Hack Sala" in available_devices_list:
            default_selection = ["Hack Sala"]
        elif available_devices_list:
            default_selection = [available_devices_list[0]]

    selected_devices_list = st.sidebar.multiselect(
        "Filtrar Dispositivos (Global)",
        options=available_devices_list,
        default=default_selection
    )
    if not selected_devices_list and app_page not in ["💡 Controle de Dispositivos", "🧾 Analisar Conta CEMIG"]:
         st.sidebar.warning("Selecione ao menos um dispositivo para carregar os dados.")
else:
    if app_page not in ["💡 Controle de Dispositivos", "🧾 Analisar Conta CEMIG"]:
        st.sidebar.info("Nenhum dispositivo encontrado para o período selecionado ou dados não disponíveis.")

data_df = pd.DataFrame()
if app_page not in ["💡 Controle de Dispositivos", "🧾 Analisar Conta CEMIG"]:
    if start_date_filter and end_date_filter and start_date_filter <= end_date_filter and selected_devices_list:
        data_df = load_data(start_date_filter, end_date_filter, selected_devices_list)
    elif not selected_devices_list and available_devices_list:
        st.sidebar.info("Selecione dispositivos no filtro global para carregar dados.")

# --- Page Routing ---
if app_page == "🏠 Resumo da Casa":
    show_resumo_casa(data_df, selected_devices_list, start_date_filter, end_date_filter)

elif app_page == "🔌 Detalhes por Dispositivo":
    selected_device_for_detail = None
    options_for_detail_selectbox = available_devices_list 
    default_detail_device_index = 0
    if options_for_detail_selectbox: 
        if "Hack Sala" in selected_devices_list and "Hack Sala" in options_for_detail_selectbox:
            default_detail_device_index = options_for_detail_selectbox.index("Hack Sala")
        elif selected_devices_list and selected_devices_list[0] in options_for_detail_selectbox:
            default_detail_device_index = options_for_detail_selectbox.index(selected_devices_list[0])
        selected_device_for_detail = st.sidebar.selectbox(
            "Selecione um Dispositivo para Detalhes:",
            options=options_for_detail_selectbox,
            index=default_detail_device_index
        )
    show_detalhes_dispositivo(data_df, selected_device_for_detail, start_date_filter, end_date_filter)

elif app_page == "📊 Análise Avançada":
    show_analise_avancada(data_df, selected_devices_list, start_date_filter, end_date_filter)
    st.markdown("---")
    st.subheader("Perfis Multicanais de Energia (kWh)") 
    devices_for_multichannel_select = selected_devices_list if selected_devices_list else available_devices_list
    if devices_for_multichannel_select:
        multichannel_device = st.selectbox(
            "Selecione um dispositivo para os Perfis Multicanais:", 
            options=devices_for_multichannel_select, 
            key="multichannel_device_selector_combined"
        )
        if multichannel_device and not data_df.empty:
            device_specific_df_for_multichannel = data_df[data_df['device_name'] == multichannel_device]
            if not device_specific_df_for_multichannel.empty:
                st.markdown("##### Perfis Semanais Sobrepostos 2D")
                help_text_2d_overlay = "Este gráfico 2D sobrepõe os perfis de consumo de energia (kWh) para cada hora da semana (168 canais) para as últimas semanas selecionadas. Permite comparar diretamente os padrões semanais."
                st.subheader("Perfis Semanais Sobrepostos 2D", help=help_text_2d_overlay)
                fig_2d_overlay = generate_2d_overlaid_weekly_profiles_plot(device_specific_df_for_multichannel, start_date_filter, end_date_filter)
                if fig_2d_overlay.data:
                    st.plotly_chart(fig_2d_overlay, use_container_width=True, key="multichannel_2d_overlay_plot") 
                else:
                    st.info(f"Não foi possível gerar o gráfico de perfis sobrepostos 2D para '{multichannel_device}'. Verifique os dados.")
                st.markdown("---")
                st.markdown("##### Perfil Estatístico Multicanal 2D (Média Histórica, Desvios e Semana Atual)")
                help_text_2d_statistical = "Este gráfico 2D mostra a média histórica (EWMA) do consumo de energia (kWh) para cada hora da semana (168 canais), com bandas de desvio padrão. A linha da semana atual é sobreposta para comparação com o padrão histórico."
                st.subheader("Perfil Estatístico Semanal 2D", help=help_text_2d_statistical)
                fig_2d_weekly_profile, fig_daily_profiles = generate_2d_statistical_profile_plot(device_specific_df_for_multichannel, start_date_filter, end_date_filter)
                if fig_2d_weekly_profile.data:
                    st.plotly_chart(fig_2d_weekly_profile, use_container_width=True, key="multichannel_2d_weekly_statistical_plot")
                else:
                    st.info(f"Não foi possível gerar o perfil estatístico semanal 2D para '{multichannel_device}'. Verifique os dados.")
                st.markdown("---")
                st.subheader("Perfis Médios Diários 2D", help="Estes gráficos mostram o perfil médio de consumo (kW) para cada hora de cada dia da semana.")
                if fig_daily_profiles.data:
                    st.plotly_chart(fig_daily_profiles, use_container_width=True, key="multichannel_2d_daily_profiles_plot")
                else:
                    st.info(f"Não foi possível gerar os perfis diários 2D para '{multichannel_device}'. Verifique os dados.")
                st.markdown("---")
                st.markdown("##### Perfis Semanais 3D (Média Histórica e Últimas Semanas Individuais)")
                help_text_3d = "Este gráfico 3D exibe a média histórica (EWMA) do consumo de energia (kWh) para cada hora da semana e os perfis individuais das últimas 4 semanas. Permite a visualização de tendências e desvios recentes em relação à média."
                st.subheader("Perfis Semanais 3D", help=help_text_3d)
                fig_3d_profiles, hist_avg_plotted = generate_3d_multichannel_profiles_plot(device_specific_df_for_multichannel, start_date_filter, end_date_filter)
                if fig_3d_profiles.data:
                    st.plotly_chart(fig_3d_profiles, use_container_width=True, key="multichannel_3d_profiles_plot") 
                    if not hist_avg_plotted:
                         st.caption("Nota: Média histórica não pôde ser calculada/plotada devido a dados insuficientes.")
                else:
                    st.info(f"Não foi possível gerar os perfis 3D para '{multichannel_device}'. Verifique os dados.")
            else:
                st.info(f"Nenhum dado de potência encontrado para '{multichannel_device}' no período selecionado para os perfis multicanais.")
        elif data_df.empty and multichannel_device:
             st.info(f"Dados globais não carregados. Selecione dispositivos no filtro geral e tente novamente para ver os perfis de '{multichannel_device}'.")
        else:
            st.info("Selecione um dispositivo para visualizar os perfis multicanais.")
    else:
        st.info("Nenhum dispositivo disponível para seleção. Verifique os filtros globais.")

elif app_page == "💡 Controle de Dispositivos":
    st.header("Controle de Dispositivos e Cenas")
    st.subheader("Controle Individual de Dispositivos")
    try:
        devices = list_devices() 
        if not devices:
            actual_path_used = os.environ.get("ACTUAL_DEVICE_MAPPING_PATH_USED", "N/A (variável de caminho não definida)")
            env_path_value = os.environ.get("DEVICE_MAPPING_PATH")
            st.error("Falha ao carregar o arquivo de mapeamento de dispositivos.")
            if env_path_value:
                st.error(f"Caminho tentado via .env (DEVICE_MAPPING_PATH): '{env_path_value}'")
            st.error(f"Caminho padrão tentado: 'app/data/device_mapping.json'")
            st.error(f"Caminho absoluto que foi efetivamente usado na última tentativa: '{actual_path_used}'")
            st.error("Verifique se 'device_mapping.json' existe em um dos locais esperados e está no formato JSON correto.")
        else:
            for device in devices:
                device_id = device.get('id')
                # Assuming device_mapping.json now provides name and on_off_code
                device_name = device.get('name', 'Unknown Device')
                on_off_code = device.get('on_off_code', 'switch_led') # Default to 'switch_led' if not specified

                if device_id:
                    status = get_device_status(device_id)
                    is_on = False
                    for prop in status:
                        if prop.get('code') == on_off_code: # Use dynamic on_off_code
                            is_on = prop.get('value', False)
                            break
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**{device_name}**")
                    with col2:
                        if st.button("Ligar" if not is_on else "Desligar", key=f"toggle_{device_id}"):
                            new_status = not is_on
                            if send_device_command(device_id, on_off_code, new_status): # Use dynamic on_off_code
                                st.rerun() 
                            else:
                                st.error(f"Falha ao enviar comando para {device_name}")
                else:
                    st.warning(f"Dispositivo sem ID no mapeamento: {device_name}") 
    except ValueError as e: 
        st.error(f"Erro de configuração da API Tuya: {e}")
    except Exception as e: 
        st.error(f"Ocorreu um erro ao carregar ou controlar dispositivos: {e}")

    st.markdown("---")
    st.subheader("Gerenciamento de Cenas")
    st.subheader("Criar Nova Cena")
    scene_name = st.text_input("Nome da Cena")
    available_devices_for_scene = []
    try:
        available_devices_for_scene = list_devices()
    except Exception as e:
        st.warning(f"Não foi possível carregar a lista de dispositivos para criação de cenas: {e}")

    if available_devices_for_scene:
        selected_devices_for_scene_data = [] # Store {'id': id, 'name': name, 'on_off_code': code}
        
        options_for_multiselect = {d.get('name', 'Unknown'): d.get('id') for d in available_devices_for_scene if d.get('id')}
        selected_device_names_for_scene = st.multiselect(
            "Selecione os Dispositivos para a Cena:",
            options=list(options_for_multiselect.keys()),
            key="scene_device_multiselect"
        )
        
        for name in selected_device_names_for_scene:
            dev_id = options_for_multiselect[name]
            # Find the full device object to get on_off_code
            full_dev_obj = next((d for d in available_devices_for_scene if d.get('id') == dev_id), None)
            on_off_code = full_dev_obj.get('on_off_code', 'switch_led') if full_dev_obj else 'switch_led'
            selected_devices_for_scene_data.append({'id': dev_id, 'name': name, 'on_off_code': on_off_code})

        scene_actions = {}
        if selected_devices_for_scene_data:
            st.subheader("Definir Ações para a Cena")
            for dev_data in selected_devices_for_scene_data:
                action = st.radio(
                    f"Ação para {dev_data['name']}:",
                    options=["Ligar", "Desligar"],
                    key=f"scene_action_{dev_data['id']}" 
                )
                scene_actions[dev_data['id']] = {"code": dev_data['on_off_code'], "value": (action == "Ligar")}
        
        if st.button("Salvar Cena"):
            st.success(f"Cena '{scene_name}' salva (simulado).")
            st.write("Detalhes da Cena:")
            st.json({"name": scene_name, "actions": scene_actions})

        if scene_name and scene_actions:
            if st.button(f"Executar Cena: {scene_name}"):
                if execute_scene(scene_actions):
                    st.success(f"Cena '{scene_name}' executada com sucesso!")
                    st.rerun() 
                else:
                    st.error(f"Falha ao executar cena '{scene_name}'.")
        elif scene_name and not scene_actions and selected_devices_for_scene_names : 
             st.warning("Defina ações para os dispositivos selecionados na cena.")
        st.markdown("---")
        st.subheader("Cenas Salvas (Simulado)")
        st.write("Lista de cenas salvas aparecerá aqui.")
    else:
        st.info("Não foi possível carregar dispositivos para criar cenas (verifique o arquivo de mapeamento).")

elif app_page == "🧾 Analisar Conta CEMIG":
    st.sidebar.header("Analisar Conta CEMIG")
    uploaded_file = st.sidebar.file_uploader("Upload da Conta CEMIG (PDF)", type=["pdf"])
    if uploaded_file is not None:
        try:
            with open("temp.pdf", "wb") as f:
                f.write(uploaded_file.getbuffer())
            file_path = "temp.pdf"
            password = "0219"  
            bill_data = parse_cemig_bill(file_path, password)
            generate_report(bill_data)
        except Exception as e:
            st.error(f"Erro ao processar o arquivo: {str(e)}")
        finally:
            if os.path.exists("temp.pdf"):
                os.remove("temp.pdf")

st.sidebar.markdown("---")
st.sidebar.caption("Desenvolvido por Igor Cleto.")
