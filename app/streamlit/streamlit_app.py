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

SCHEDULED_SCENES_FILE = "app/data/scheduled_scenes.json"

def load_scenes_from_file():
    """Loads scenes from the JSON file."""
    if not os.path.exists(SCHEDULED_SCENES_FILE):
        return {}
    try:
        with open(SCHEDULED_SCENES_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        st.error(f"Erro ao decodificar o arquivo de cenas: {SCHEDULED_SCENES_FILE}. Um novo arquivo será criado se cenas forem salvas.")
        return {}
    except Exception as e:
        st.error(f"Erro inesperado ao carregar cenas: {e}")
        return {}

def save_scenes_to_file(scenes_dict):
    """Saves the entire scenes dictionary to the JSON file."""
    try:
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(SCHEDULED_SCENES_FILE), exist_ok=True)
        with open(SCHEDULED_SCENES_FILE, 'w') as f:
            json.dump(scenes_dict, f, indent=2)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar cenas no arquivo: {e}")
        return False

# Callback function for st.toggle changes
def handle_toggle_change(device_id_cb, on_off_code_cb, session_key_cb):
    """
    Called when a device toggle is changed.
    Sends the command to the device and handles success/failure by updating session_state.
    """
    # At this point, st.session_state[session_key_cb] has ALREADY been updated by the toggle
    new_state_from_toggle = st.session_state[session_key_cb]
    error_key_cb = f"error_{device_id_cb}" # Define error key based on device_id

    command_successful = send_device_command(device_id_cb, on_off_code_cb, new_state_from_toggle)
    
    if not command_successful:
        # Store an error message in session_state to be displayed by the fragment
        st.session_state[error_key_cb] = f"Falha ao enviar comando para o dispositivo."
        # Revert session state (and thus the toggle's visual state on next re-run)
        st.session_state[session_key_cb] = not new_state_from_toggle
    else:
        # Clear any previous error for this device on success
        if error_key_cb in st.session_state:
            del st.session_state[error_key_cb]

@st.fragment
def device_control_fragment(device_info):
    """Renders the control UI for a single device within a fragment, using optimistic updates."""
    device_id = device_info.get('id')
    device_name = device_info.get('name', 'Unknown Device')
    on_off_code = device_info.get('on_off_code', 'switch_led')

    if not device_id:
        st.warning(f"Dispositivo sem ID no mapeamento: {device_name}")
        return

    # Key for session state for this device's on/off status
    ss_key_device_on = f"device_on_status_{device_id}"

    # 1. Get current actual status from API
    actual_status_props = get_device_status(device_id)
    is_actually_on = False
    if actual_status_props: # Check if status was successfully fetched
        for prop in actual_status_props:
            if prop.get('code') == on_off_code:
                is_actually_on = prop.get('value', False)
                break
    else: # Could not fetch actual status, rely on session state or default to False
        if ss_key_device_on not in st.session_state:
             st.session_state[ss_key_device_on] = False # Default if API fails on first load
        # If API fails on subsequent loads, session_state will retain its last value.

    # 2. Initialize session state for the toggle if not already present.
    #    This ensures the key exists in session_state before st.toggle tries to use it.
    if ss_key_device_on not in st.session_state:
        if actual_status_props: # API call was successful
            st.session_state[ss_key_device_on] = is_actually_on
        else: # API call failed on first load for this device
            st.session_state[ss_key_device_on] = False # Default to False
    # Note: If session_state[ss_key_device_on] already exists, we let it be.
    # The on_change callback is responsible for updating it based on user interaction.
    # If the device state changes externally, the `is_actually_on` might differ from
    # session_state until the next interaction or a more sophisticated sync logic is added.
    # For optimistic UI, this is generally acceptable as on_change handles direct interaction results.

    # Key for storing error messages for this device
    error_key = f"error_{device_id}"

    # Display any error message set by the callback for this device
    if error_key in st.session_state and st.session_state[error_key]:
        st.error(st.session_state[error_key])
        del st.session_state[error_key] # Clear after displaying

    # UI: Device name in one column, toggle in another
    col1, col2 = st.columns([3, 1])
    with col1:
        st.write(f"**{device_name}**")
    with col2:
        # The toggle's state is implicitly driven by st.session_state[ss_key_device_on] due to the 'key'.
        # We DO NOT pass the 'value' argument if the key is managed in session_state.
        # The on_change callback handles the logic when the user interacts.
        st.toggle(
            label=" ", # Visually empty label
            key=ss_key_device_on, # Value is implicitly st.session_state[ss_key_device_on]
            on_change=handle_toggle_change,
            args=(device_id, on_off_code, ss_key_device_on), # Arguments for the callback
            label_visibility="collapsed"
        )

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
            for device_info in devices: # Renamed device to device_info for clarity
                device_control_fragment(device_info) # Call the fragment function for each device
    except ValueError as e: 
        st.error(f"Erro de configuração da API Tuya: {e}")
    except Exception as e: 
        st.error(f"Ocorreu um erro ao carregar ou controlar dispositivos: {e}")

    st.markdown("---")
    st.subheader("Gerenciamento de Cenas")

    # Initialize/Load scenes for the session
    if 'saved_scenes' not in st.session_state:
        st.session_state.saved_scenes = load_scenes_from_file()

    # Initialize session state for scene creation steps and temporary data
    if 'scene_creation_step' not in st.session_state:
        st.session_state.scene_creation_step = 'define'
    if 'temp_scene_name' not in st.session_state: st.session_state.temp_scene_name = ""
    if 'temp_selected_device_ids' not in st.session_state: st.session_state.temp_selected_device_ids = []
    if 'temp_scene_actions' not in st.session_state: st.session_state.temp_scene_actions = {}
    if 'temp_scene_time' not in st.session_state: st.session_state.temp_scene_time = None
    if 'temp_scene_days' not in st.session_state: st.session_state.temp_scene_days = []
    if 'temp_scene_recurring' not in st.session_state: st.session_state.temp_scene_recurring = True

    # Fetch all device details once for name lookup and multiselect options for this section
    # This list_devices() call might be redundant if already called for individual controls,
    # but ensures this section has the data it needs independently.
    all_devices_details_list_scene = list_devices() 
    device_id_to_name_map_scene = {
        dev['id']: dev['name'] 
        for dev in all_devices_details_list_scene 
        if isinstance(dev, dict) and 'id' in dev and 'name' in dev
    }
    multiselect_options_scene = {dev_name: dev_id for dev_id, dev_name in device_id_to_name_map_scene.items()} # Corrected: use dev_name and dev_id

    if st.session_state.scene_creation_step == 'define':
        with st.form(key="define_scene_form"):
            st.subheader("Criar Nova Cena: Detalhes")
            scene_name_input = st.text_input(
                "Nome da Cena", 
                value=st.session_state.temp_scene_name,
                key="scene_name_create_input" # Consistent keying
            )
            
            selected_device_names_form = st.multiselect(
                "Selecione os Dispositivos para a Cena:",
                options=list(multiselect_options_scene.keys()),
                default=[device_id_to_name_map_scene[dev_id] for dev_id in st.session_state.temp_selected_device_ids if dev_id in device_id_to_name_map_scene], # Pre-fill from temp state
                key="scene_devices_create_multiselect"
            )
            
            current_scene_actions = {} 
            if selected_device_names_form:
                st.write("Definir Ações para os Dispositivos Selecionados:")
                for dev_name in selected_device_names_form:
                    dev_id = multiselect_options_scene[dev_name]
                    # Find full device object for on_off_code
                    full_dev_obj = next((d for d in all_devices_details_list_scene if d.get('id') == dev_id), None)
                    on_off_code = full_dev_obj.get('on_off_code', 'switch_led') if full_dev_obj else 'switch_led'
                    
                    # Default action for radio from temp_scene_actions or 'Desligar'
                    default_action_value = st.session_state.temp_scene_actions.get(dev_id, {}).get('value', False)
                    action_radio_index = 0 if default_action_value else 1 # Ligar is True (index 0), Desligar is False (index 1)
                    
                    action_str = st.radio(
                        f"Ação para {dev_name}:",
                        options=["Ligar", "Desligar"],
                        index=action_radio_index,
                        key=f"scene_action_radio_create_{dev_id}" # Unique key
                    )
                    current_scene_actions[dev_id] = {"code": on_off_code, "value": (action_str == "Ligar")}
            
            st.markdown("---")
            st.write("Definir Horário da Cena (Opcional):")
            scene_time = st.time_input(
                "Horário para acionar a cena:", 
                value=st.session_state.temp_scene_time,
                key="scene_time_create_input"
            )
            scene_days = st.multiselect(
                "Dias da semana para acionar (deixe em branco se não for recorrente ou para hoje/próximo):",
                options=["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"],
                default=st.session_state.temp_scene_days,
                key="scene_days_create_multiselect"
            )
            scene_recurring = st.checkbox(
                "Repetir semanalmente nos dias selecionados", 
                value=st.session_state.temp_scene_recurring,
                key="scene_recurring_create_checkbox"
            )

            if st.form_submit_button("Revisar Ações e Horário da Cena"):
                if not scene_name_input:
                    st.warning("Por favor, dê um nome para a cena.")
                elif not selected_device_names_form: # Check if devices were selected
                    st.warning("Por favor, selecione dispositivos para a cena.")
                elif not current_scene_actions: # Check if actions were defined for selected devices
                     st.warning("Defina ações para os dispositivos selecionados.")
                else:
                    st.session_state.temp_scene_name = scene_name_input
                    st.session_state.temp_selected_device_ids = [multiselect_options_scene[name] for name in selected_device_names_form]
                    st.session_state.temp_scene_actions = current_scene_actions
                    st.session_state.temp_scene_time = scene_time
                    st.session_state.temp_scene_days = scene_days
                    st.session_state.temp_scene_recurring = scene_recurring
                    st.session_state.scene_creation_step = 'review'
                    st.rerun()

    elif st.session_state.scene_creation_step == 'review':
        st.subheader(f"Revisar Cena: {st.session_state.temp_scene_name}")
        
        st.markdown("**Ações Definidas:**")
        if not st.session_state.temp_scene_actions:
            st.write("Nenhuma ação definida.")
        else:
            for dev_id, action_details in st.session_state.temp_scene_actions.items():
                dev_name = device_id_to_name_map_scene.get(dev_id, f"Dispositivo (ID: {dev_id})")
                action_str = "Ligar" if action_details.get('value') else "Desligar"
                st.write(f"- **{dev_name}**: {action_str}")
        
        st.markdown("**Horário Definido:**")
        if st.session_state.temp_scene_time:
            st.write(f"Horário: {st.session_state.temp_scene_time.strftime('%H:%M')}")
            if st.session_state.temp_scene_days:
                st.write(f"Dias: {', '.join(st.session_state.temp_scene_days)}")
                if st.session_state.temp_scene_recurring:
                    st.write("Repetir: Semanalmente")
                else:
                    st.write("Repetir: Não (apenas na próxima ocorrência dos dias/horário selecionados)")
            else:
                st.write("Repetir: Apenas uma vez no próximo horário selecionado.")
        else:
            st.write("Nenhum horário específico definido (acionamento manual).")

        st.markdown("---")
        col1_review, col2_review = st.columns(2)
        with col1_review:
            if st.button("Modificar Detalhes"):
                # temp_values are already in session_state, so 'define' step will pre-fill
                st.session_state.scene_creation_step = 'define'
                st.rerun()
        with col2_review:
            if st.button("Salvar Cena Definitivamente"):
                scene_to_save = {
                    "actions": st.session_state.temp_scene_actions,
                    "schedule": {
                        "time": st.session_state.temp_scene_time.strftime('%H:%M') if st.session_state.temp_scene_time else None,
                        "days": st.session_state.temp_scene_days,
                        "recurring": st.session_state.temp_scene_recurring
                    }
                }
                if 'saved_scenes' not in st.session_state: # Should already be initialized
                    st.session_state.saved_scenes = {}
                st.session_state.saved_scenes[st.session_state.temp_scene_name] = scene_to_save
                
                if save_scenes_to_file(st.session_state.saved_scenes):
                    st.success(f"Cena '{st.session_state.temp_scene_name}' salva permanentemente!")
                else:
                    st.error(f"Cena '{st.session_state.temp_scene_name}' salva na sessão atual, mas falha ao salvar permanentemente.")

                # Reset temp states for next creation
                st.session_state.temp_scene_name = ""
                st.session_state.temp_selected_device_ids = []
                st.session_state.temp_scene_actions = {}
                st.session_state.temp_scene_time = None
                st.session_state.temp_scene_days = []
                st.session_state.temp_scene_recurring = True # Reset to default
                st.session_state.scene_creation_step = 'define'
                st.rerun()

    # Scene Execution - operates on saved scenes
    st.markdown("---")
    st.subheader("Executar Cena Salva")
    if 'saved_scenes' in st.session_state and st.session_state.saved_scenes:
        scene_to_execute_name = st.selectbox(
            "Selecione uma cena para executar:",
            options=list(st.session_state.saved_scenes.keys()),
            key="execute_scene_selector"
        )
        if scene_to_execute_name:
            actions_to_execute = st.session_state.saved_scenes[scene_to_execute_name]
            if st.button(f"Executar Cena: {scene_to_execute_name}", key="execute_saved_scene_button"):
                if execute_scene(actions_to_execute):
                    st.success(f"Cena '{scene_to_execute_name}' executada com sucesso!")
                    st.rerun() 
                else:
                    st.error(f"Falha ao executar cena '{scene_to_execute_name}'.")
    else:
        st.info("Nenhuma cena salva para executar. Crie e salve uma cena primeiro.")

    st.markdown("---")
    st.subheader("Cenas Salvas")
    if 'saved_scenes' in st.session_state and st.session_state.saved_scenes:
        # Fetch all device details once for name lookup, if not already available
        # This could be optimized by fetching it once per page load if needed elsewhere too
        all_devices_details_list = list_devices() 
        device_id_to_name_map = {
            dev['id']: dev['name'] 
            for dev in all_devices_details_list 
            if isinstance(dev, dict) and 'id' in dev and 'name' in dev # Using device_id_to_name_map_scene now
        }

        for scene_name_saved, scene_data_saved in st.session_state.saved_scenes.items():
            with st.expander(f"Cena: {scene_name_saved}"):
                scene_actions_saved = scene_data_saved.get("actions", {})
                scene_schedule_saved = scene_data_saved.get("schedule", {})

                if not scene_actions_saved:
                    st.write("Nenhuma ação definida para esta cena.")
                else:
                    st.markdown("**Ações:**")
                    for device_id_action, action_details in scene_actions_saved.items():
                        # Use device_id_to_name_map_scene for consistency
                        device_name_action = device_id_to_name_map_scene.get(device_id_action, f"Dispositivo (ID: {device_id_action})")
                        action_value_str = "Ligar" if action_details.get('value', False) else "Desligar"
                        st.write(f"- **{device_name_action}**: {action_value_str}")
                
                if scene_schedule_saved and scene_schedule_saved.get("time"):
                    st.markdown("**Horário Agendado:**")
                    st.write(f"Horário: {scene_schedule_saved['time']}")
                    if scene_schedule_saved.get("days"):
                        st.write(f"Dias: {', '.join(scene_schedule_saved['days'])}")
                        st.write(f"Repetir: {'Semanalmente' if scene_schedule_saved.get('recurring') else 'Não'}")
                    else:
                        st.write("Repetir: Apenas uma vez no próximo horário.")
                else:
                    st.write("Nenhum horário agendado (acionamento manual).")
    else:
        st.write("Nenhuma cena salva ainda.")

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
