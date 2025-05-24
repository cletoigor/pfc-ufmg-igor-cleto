import streamlit as st
import pandas as pd
import os
import json
from datetime import datetime, timedelta, time as dt_time_obj

# Import refactored functions
from utils.data_helpers import load_data, get_available_devices, parse_cemig_bill, generate_report
from utils.ui_helpers import local_css
from utils.page_functions import show_resumo_casa, show_detalhes_dispositivo, show_analise_avancada, generate_2d_statistical_profile_plot, generate_3d_multichannel_profiles_plot, generate_2d_overlaid_weekly_profiles_plot
from utils.tuya_api_helpers import list_devices, get_device_status, send_device_command, execute_scene

# --- Streamlit App UI ---

SCHEDULED_SCENES_FILE = "app/streamlit/app/data/scheduled_scenes.json"

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
        os.makedirs(os.path.dirname(SCHEDULED_SCENES_FILE), exist_ok=True)
        with open(SCHEDULED_SCENES_FILE, 'w') as f:
            json.dump(scenes_dict, f, indent=2)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar cenas no arquivo: {e}")
        return False

# Callback function for st.toggle changes
def handle_toggle_change(device_id_cb, on_off_code_cb, session_key_cb):
    new_state_from_toggle = st.session_state[session_key_cb]
    error_key_cb = f"error_{device_id_cb}"
    command_successful = send_device_command(device_id_cb, on_off_code_cb, new_state_from_toggle)
    if not command_successful:
        st.session_state[error_key_cb] = f"Falha ao enviar comando para o dispositivo."
        st.session_state[session_key_cb] = not new_state_from_toggle
    else:
        if error_key_cb in st.session_state:
            del st.session_state[error_key_cb]

@st.fragment
def device_control_fragment(device_info):
    device_id = device_info.get('id')
    device_name = device_info.get('name', 'Unknown Device')
    on_off_code = device_info.get('on_off_code', 'switch_led')
    if not device_id:
        st.warning(f"Dispositivo sem ID no mapeamento: {device_name}")
        return
    ss_key_device_on = f"device_on_status_{device_id}"
    actual_status_props = get_device_status(device_id)
    is_actually_on = False
    if actual_status_props:
        for prop in actual_status_props:
            if prop.get('code') == on_off_code:
                is_actually_on = prop.get('value', False)
                break
    else:
        if ss_key_device_on not in st.session_state:
             st.session_state[ss_key_device_on] = False
    if ss_key_device_on not in st.session_state:
        st.session_state[ss_key_device_on] = is_actually_on if actual_status_props else False
    error_key = f"error_{device_id}"
    if error_key in st.session_state and st.session_state[error_key]:
        st.error(st.session_state[error_key])
        del st.session_state[error_key]
    col1, col2 = st.columns([3, 1])
    with col1:
        st.write(f"**{device_name}**")
    with col2:
        st.toggle(label=" ", key=ss_key_device_on, on_change=handle_toggle_change,
                    args=(device_id, on_off_code, ss_key_device_on), label_visibility="collapsed")

st.set_page_config(layout="wide", page_title="Análise de Energia Residencial")
try:
    with open("style.css") as f: css = f.read()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    st.warning("Arquivo style.css não encontrado. Estilos personalizados não serão aplicados.")

st.title("Análise de Consumo de Energia Residencial")

st.sidebar.header("Navegação")
main_menu = st.sidebar.radio("Selecione o Menu", ["📊 Relatórios", "💡 Acionamentos"], key="main_menu_key")
app_page = None
if main_menu == "📊 Relatórios":
    app_page = st.sidebar.radio("Selecione a Página de Relatório",
                                ["🏠 Resumo da Casa", "🔌 Detalhes por Dispositivo", "📊 Análise Avançada", "🧾 Analisar Conta CEMIG"],
                                key="report_page_selector")
elif main_menu == "💡 Acionamentos":
    app_page = st.sidebar.radio("Selecione a Página de Acionamento", ["💡 Controle de Dispositivos"], key="action_page_selector")

st.sidebar.header("Filtros Gerais")
today = datetime.now().date()
default_period_options = {
    "Hoje": (today, today), "Ontem": (today - timedelta(days=1), today - timedelta(days=1)),
    "Últimos 7 Dias": (today - timedelta(days=6), today), "Este Mês": (today.replace(day=1), today),
    "Mês Anterior": ((today.replace(day=1) - timedelta(days=1)).replace(day=1), today.replace(day=1) - timedelta(days=1)),
    "Período Customizado": None
}
default_period_key = "Últimos 7 Dias"
selected_period_label = st.sidebar.selectbox("Selecione o Período:", options=list(default_period_options.keys()),
                                             index=list(default_period_options.keys()).index(default_period_key), key="period_selectbox")
if selected_period_label == "Período Customizado":
    start_date_filter = st.sidebar.date_input("Data Inicial Customizada", value=today - timedelta(days=6), key="custom_start_date")
    end_date_filter = st.sidebar.date_input("Data Final Customizada", value=today, key="custom_end_date")
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
    if app_page == "🏠 Resumo da Casa": default_selection = available_devices_list
    elif app_page and app_page != "💡 Controle de Dispositivos" and app_page != "🧾 Analisar Conta CEMIG":
        if "Hack Sala" in available_devices_list: default_selection = ["Hack Sala"]
        elif available_devices_list: default_selection = [available_devices_list[0]]
    selected_devices_list = st.sidebar.multiselect("Filtrar Dispositivos (Global)", options=available_devices_list, default=default_selection, key="global_device_multiselect")
    if not selected_devices_list and app_page not in ["💡 Controle de Dispositivos", "🧾 Analisar Conta CEMIG"]:
         st.sidebar.warning("Selecione ao menos um dispositivo para carregar os dados.")
elif app_page not in ["💡 Controle de Dispositivos", "🧾 Analisar Conta CEMIG"]:
    st.sidebar.info("Nenhum dispositivo encontrado para o período selecionado ou dados não disponíveis.")

data_df = pd.DataFrame()
if app_page not in ["💡 Controle de Dispositivos", "🧾 Analisar Conta CEMIG"]:
    if start_date_filter and end_date_filter and start_date_filter <= end_date_filter and selected_devices_list:
        data_df = load_data(start_date_filter, end_date_filter, selected_devices_list)
    elif not selected_devices_list and available_devices_list:
        st.sidebar.info("Selecione dispositivos no filtro global para carregar dados.")

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
            index=default_detail_device_index,
            key="detail_device_selectbox"
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
                st.subheader("Perfis Semanais Sobrepostos 2D", help="Este gráfico 2D sobrepõe os perfis de consumo de energia (kWh) para cada hora da semana (168 canais) para as últimas semanas selecionadas. Permite comparar diretamente os padrões semanais.")
                fig_2d_overlay = generate_2d_overlaid_weekly_profiles_plot(device_specific_df_for_multichannel, start_date_filter, end_date_filter)
                if fig_2d_overlay.data: st.plotly_chart(fig_2d_overlay, use_container_width=True, key="multichannel_2d_overlay_plot") 
                else: st.info(f"Não foi possível gerar o gráfico de perfis sobrepostos 2D para '{multichannel_device}'. Verifique os dados.")
                st.markdown("---")
                st.markdown("##### Perfil Estatístico Multicanal 2D (Média Histórica, Desvios e Semana Atual)")
                st.subheader("Perfil Estatístico Semanal 2D", help="Este gráfico 2D mostra a média histórica (EWMA) do consumo de energia (kWh) para cada hora da semana (168 canais), com bandas de desvio padrão. A linha da semana atual é sobreposta para comparação com o padrão histórico.")
                fig_2d_weekly_profile, fig_daily_profiles = generate_2d_statistical_profile_plot(device_specific_df_for_multichannel, start_date_filter, end_date_filter)
                if fig_2d_weekly_profile.data: st.plotly_chart(fig_2d_weekly_profile, use_container_width=True, key="multichannel_2d_weekly_statistical_plot")
                else: st.info(f"Não foi possível gerar o perfil estatístico semanal 2D para '{multichannel_device}'. Verifique os dados.")
                st.markdown("---")
                st.subheader("Perfis Médios Diários 2D", help="Estes gráficos mostram o perfil médio de consumo (kW) para cada hora de cada dia da semana.")
                if fig_daily_profiles.data: st.plotly_chart(fig_daily_profiles, use_container_width=True, key="multichannel_2d_daily_profiles_plot")
                else: st.info(f"Não foi possível gerar os perfis diários 2D para '{multichannel_device}'. Verifique os dados.")
                st.markdown("---")
                st.markdown("##### Perfis Semanais 3D (Média Histórica e Últimas Semanas Individuais)")
                st.subheader("Perfis Semanais 3D", help="Este gráfico 3D exibe a média histórica (EWMA) do consumo de energia (kWh) para cada hora da semana e os perfis individuais das últimas 4 semanas. Permite a visualização de tendências e desvios recentes em relação à média.")
                fig_3d_profiles, hist_avg_plotted = generate_3d_multichannel_profiles_plot(device_specific_df_for_multichannel, start_date_filter, end_date_filter)
                if fig_3d_profiles.data:
                    st.plotly_chart(fig_3d_profiles, use_container_width=True, key="multichannel_3d_profiles_plot") 
                    if not hist_avg_plotted: st.caption("Nota: Média histórica não pôde ser calculada/plotada devido a dados insuficientes.")
                else: st.info(f"Não foi possível gerar os perfis 3D para '{multichannel_device}'. Verifique os dados.")
            else: st.info(f"Nenhum dado de potência encontrado para '{multichannel_device}' no período selecionado para os perfis multicanais.")
        elif data_df.empty and multichannel_device: st.info(f"Dados globais não carregados. Selecione dispositivos no filtro geral e tente novamente para ver os perfis de '{multichannel_device}'.")
        else: st.info("Selecione um dispositivo para visualizar os perfis multicanais.")
    else: st.info("Nenhum dispositivo disponível para seleção. Verifique os filtros globais.")

elif app_page == "💡 Controle de Dispositivos":
    st.header("Controle de Dispositivos e Cenas")
    st.subheader("Controle Individual de Dispositivos")
    try:
        devices_list_individual = list_devices() 
        if not devices_list_individual:
            st.error("Falha ao carregar lista de dispositivos para controle individual.")
        else:
            for device_info in devices_list_individual:
                device_control_fragment(device_info)
    except Exception as e: 
        st.error(f"Ocorreu um erro ao carregar ou controlar dispositivos: {e}")

    st.markdown("---")
    st.subheader("Gerenciamento de Cenas")

    if 'saved_scenes' not in st.session_state:
        st.session_state.saved_scenes = load_scenes_from_file()

    # Initialize states for multi-step scene creation
    if 'scene_creation_step' not in st.session_state: st.session_state.scene_creation_step = 'step1_name_devices'
    if 'temp_scene_name' not in st.session_state: st.session_state.temp_scene_name = ""
    if 'temp_selected_device_ids' not in st.session_state: st.session_state.temp_selected_device_ids = []
    if 'temp_scene_actions' not in st.session_state: st.session_state.temp_scene_actions = {}
    if 'temp_scene_schedule_time' not in st.session_state: st.session_state.temp_scene_schedule_time = None
    if 'temp_scene_schedule_days' not in st.session_state: st.session_state.temp_scene_schedule_days = []
    if 'temp_scene_schedule_recurring' not in st.session_state: st.session_state.temp_scene_schedule_recurring = False
    if 'confirm_delete_scene_name' not in st.session_state: st.session_state.confirm_delete_scene_name = None


    all_devices_list_for_scenes = list_devices()
    device_id_to_name_map_for_scenes = {dev['id']: dev['name'] for dev in all_devices_list_for_scenes if isinstance(dev, dict) and 'id' in dev and 'name' in dev}
    device_name_to_id_map_for_scenes = {name: id_ for id_, name in device_id_to_name_map_for_scenes.items()}

    if st.session_state.scene_creation_step == 'step1_name_devices':
        with st.form(key="scene_step1_form"):
            st.subheader("Passo 1: Nome da Cena e Dispositivos")
            scene_name = st.text_input("Nome da Cena", value=st.session_state.temp_scene_name, key="ss_scene_name_step1_input")
            default_names_step1 = [device_id_to_name_map_for_scenes[id_] for id_ in st.session_state.temp_selected_device_ids if id_ in device_id_to_name_map_for_scenes]
            selected_device_names = st.multiselect(
                "Selecione os Dispositivos", 
                options=list(device_name_to_id_map_for_scenes.keys()), 
                default=default_names_step1,
                key="ss_scene_devices_step1_multiselect"
            )
            if st.form_submit_button("Próximo: Definir Horário e Ações"):
                if not scene_name.strip(): st.warning("Por favor, insira um nome para a cena.")
                elif not selected_device_names: st.warning("Por favor, selecione pelo menos um dispositivo para a cena.")
                else:
                    st.session_state.temp_scene_name = scene_name.strip()
                    st.session_state.temp_selected_device_ids = [device_name_to_id_map_for_scenes[name] for name in selected_device_names]
                    updated_actions = {}
                    for dev_id in st.session_state.temp_selected_device_ids:
                        full_dev_obj = next((d for d in all_devices_list_for_scenes if d.get('id') == dev_id), None)
                        on_off_code = full_dev_obj.get('on_off_code', 'switch_led') if full_dev_obj else 'switch_led'
                        updated_actions[dev_id] = st.session_state.temp_scene_actions.get(dev_id, {"code": on_off_code, "value": False})
                    st.session_state.temp_scene_actions = updated_actions
                    st.session_state.scene_creation_step = 'step2_schedule_actions'
                    st.rerun()

    elif st.session_state.scene_creation_step == 'step2_schedule_actions':
        st.subheader(f"Passo 2: Horário e Ações para '{st.session_state.temp_scene_name}'")
        with st.form(key="scene_step2_form"):
            st.write("**Definir Horário (Opcional):**")
            schedule_time = st.time_input("Horário:", value=st.session_state.temp_scene_schedule_time, key="ss_scene_time_step2_input")
            schedule_days = st.multiselect("Dias da semana:", options=["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"], default=st.session_state.temp_scene_schedule_days, key="ss_scene_days_step2_multiselect")
            schedule_recurring = st.checkbox("Repetir semanalmente", value=st.session_state.temp_scene_schedule_recurring, key="ss_scene_recurring_step2_check")
            st.markdown("---")
            st.write("**Definir Ações para Dispositivos:**")
            current_actions_step2 = {}
            if not st.session_state.temp_selected_device_ids:
                st.info("Nenhum dispositivo selecionado no passo anterior.")
            else:
                for dev_id in st.session_state.temp_selected_device_ids:
                    dev_name = device_id_to_name_map_for_scenes.get(dev_id, "Dispositivo Desconhecido")
                    full_dev_obj = next((d for d in all_devices_list_for_scenes if d.get('id') == dev_id), None)
                    on_off_code = full_dev_obj.get('on_off_code', 'switch_led') if full_dev_obj else 'switch_led'
                    default_action_val = st.session_state.temp_scene_actions.get(dev_id, {}).get('value', False)
                    action_idx = 0 if default_action_val else 1
                    action_str = st.radio(f"Ação para {dev_name}:", ["Ligar", "Desligar"], index=action_idx, key=f"ss_action_step2_radio_{dev_id}")
                    current_actions_step2[dev_id] = {"code": on_off_code, "value": (action_str == "Ligar")}
            
            col_back_s2, col_next_s2 = st.columns(2)
            with col_back_s2:
                if st.form_submit_button("Voltar (Nome e Dispositivos)"):
                    st.session_state.temp_scene_schedule_time = schedule_time
                    st.session_state.temp_scene_schedule_days = schedule_days
                    st.session_state.temp_scene_schedule_recurring = schedule_recurring
                    st.session_state.temp_scene_actions = current_actions_step2
                    st.session_state.scene_creation_step = 'step1_name_devices'
                    st.rerun()
            with col_next_s2:
                submitted_step2_next = st.form_submit_button("Próximo: Revisar Cena")

        if submitted_step2_next: 
            if not current_actions_step2 and st.session_state.temp_selected_device_ids :
                st.warning("Defina ações para todos os dispositivos selecionados.")
            else:
                st.session_state.temp_scene_schedule_time = schedule_time
                st.session_state.temp_scene_schedule_days = schedule_days
                st.session_state.temp_scene_schedule_recurring = schedule_recurring
                st.session_state.temp_scene_actions = current_actions_step2
                st.session_state.scene_creation_step = 'step3_review'
                st.rerun()

    elif st.session_state.scene_creation_step == 'step3_review':
        st.subheader(f"Passo 3: Revisar Cena '{st.session_state.temp_scene_name}'")
        st.markdown(f"**Nome da Cena:** {st.session_state.temp_scene_name}")
        st.markdown("**Dispositivos e Ações:**")
        if not st.session_state.temp_scene_actions: st.write("Nenhuma ação definida.")
        else:
            for dev_id, action_details in st.session_state.temp_scene_actions.items():
                dev_name = device_id_to_name_map_for_scenes.get(dev_id, f"ID: {dev_id}")
                action_str = "Ligar" if action_details.get('value') else "Desligar"
                st.write(f"- {dev_name}: **{action_str}**")
        st.markdown("**Horário Agendado:**")
        if st.session_state.temp_scene_schedule_time:
            time_str = st.session_state.temp_scene_schedule_time.strftime('%H:%M')
            st.write(f"Horário: {time_str}")
            if st.session_state.temp_scene_schedule_days:
                st.write(f"Dias: {', '.join(st.session_state.temp_scene_schedule_days)}")
                st.write(f"Repetir: {'Semanalmente nos dias indicados' if st.session_state.temp_scene_schedule_recurring else 'Uma vez nos dias indicados'}")
            else: st.write("Repetir: Apenas uma vez no próximo horário indicado.")
        else: st.write("Nenhum horário definido (acionamento manual).")
        st.markdown("---")
        col_modify, col_save_final = st.columns(2)
        with col_modify:
            if st.button("Modificar Detalhes", key="modify_details_step3_btn"):
                st.session_state.scene_creation_step = 'step1_name_devices'
                st.rerun()
        with col_save_final:
            if st.button("Salvar Cena Definitivamente", key="save_final_step3_btn"):
                scene_data_to_save = {
                    "actions": st.session_state.temp_scene_actions,
                    "schedule": {
                        "time": st.session_state.temp_scene_schedule_time.strftime('%H:%M') if st.session_state.temp_scene_schedule_time else None,
                        "days": st.session_state.temp_scene_schedule_days,
                        "recurring": st.session_state.temp_scene_schedule_recurring
                    }
                }
                if 'saved_scenes' not in st.session_state:
                    st.session_state.saved_scenes = load_scenes_from_file() # Ensure it's loaded before adding
                st.session_state.saved_scenes[st.session_state.temp_scene_name] = scene_data_to_save
                if save_scenes_to_file(st.session_state.saved_scenes):
                    st.success(f"Cena '{st.session_state.temp_scene_name}' salva permanentemente!")
                else:
                    st.error(f"Cena '{st.session_state.temp_scene_name}' salva na sessão, mas falha ao salvar permanentemente.")
                st.session_state.scene_creation_step = 'step1_name_devices'
                st.session_state.temp_scene_name = ""
                st.session_state.temp_selected_device_ids = []
                st.session_state.temp_scene_actions = {}
                st.session_state.temp_scene_schedule_time = None
                st.session_state.temp_scene_schedule_days = []
                st.session_state.temp_scene_schedule_recurring = False
                if 'confirm_delete_scene_name' in st.session_state: del st.session_state.confirm_delete_scene_name
                st.rerun()

    st.markdown("---")
    st.subheader("Executar Cena Salva")
    if not st.session_state.get('saved_scenes'): st.info("Nenhuma cena salva para executar.")
    else:
        scene_to_execute_name = st.selectbox("Selecione uma cena para executar:", options=list(st.session_state.saved_scenes.keys()), key="exec_scene_select")
        if scene_to_execute_name:
            scene_data_for_exec = st.session_state.saved_scenes[scene_to_execute_name]
            actions_to_execute = scene_data_for_exec.get("actions", {})
            if st.button(f"Executar Cena: {scene_to_execute_name}", key="exec_scene_btn"):
                if actions_to_execute:
                    if execute_scene(actions_to_execute):
                        st.success(f"Cena '{scene_to_execute_name}' executada com sucesso!")
                        st.rerun() # This will ensure the whole page updates, including fragments with changed session state.
                                   # The fragments will pick up their new session state values.
                    else: 
                        st.error(f"Falha ao executar cena '{scene_to_execute_name}'.")
                else: 
                    st.info("Nenhuma ação definida para esta cena.")

    if not st.session_state.get('saved_scenes'): st.write("Nenhuma cena salva ainda.")
    else:
        for scene_name_saved, scene_data_saved in st.session_state.saved_scenes.items():
            if st.session_state.get('confirm_delete_scene_name') == scene_name_saved: continue
            with st.expander(f"Cena: {scene_name_saved}"):
                scene_actions_saved = scene_data_saved.get("actions", {})
                scene_schedule_saved = scene_data_saved.get("schedule", {})
                if not scene_actions_saved: st.write("Nenhuma ação definida.")
                else:
                    st.markdown("**Ações:**")
                    for dev_id, action_details in scene_actions_saved.items():
                        dev_name = device_id_to_name_map_for_scenes.get(dev_id, f"ID: {dev_id}")
                        action_str = "Ligar" if action_details.get('value') else "Desligar"
                        st.write(f"- **{dev_name}**: {action_str}")
                if scene_schedule_saved and scene_schedule_saved.get("time"):
                    st.markdown("**Horário Agendado:**")
                    st.write(f"Horário: {scene_schedule_saved['time']}")
                    if scene_schedule_saved.get("days"):
                        st.write(f"Dias: {', '.join(scene_schedule_saved['days'])}")
                        st.write(f"Repetir: {'Semanalmente nos dias indicados' if scene_schedule_saved.get('recurring') else 'Uma vez nos dias indicados'}")
                    else: st.write("Repetir: Apenas uma vez no próximo horário indicado.")
                else: st.write("Nenhum horário agendado (acionamento manual).")
                if st.button("🗑️ Excluir esta Cena", key=f"delete_btn_{scene_name_saved}"):
                    st.session_state.confirm_delete_scene_name = scene_name_saved
                    st.rerun()

elif app_page == "🧾 Analisar Conta CEMIG":
    st.sidebar.header("Analisar Conta CEMIG")
    uploaded_file = st.sidebar.file_uploader("Upload da Conta CEMIG (PDF)", type=["pdf"])
    if uploaded_file is not None:
        try:
            with open("temp.pdf", "wb") as f: f.write(uploaded_file.getbuffer())
            file_path = "temp.pdf"
            password = "0219"  
            bill_data = parse_cemig_bill(file_path, password)
            generate_report(bill_data)
        except Exception as e: st.error(f"Erro ao processar o arquivo: {str(e)}")
        finally:
            if os.path.exists("temp.pdf"): os.remove("temp.pdf")

st.sidebar.markdown("---")
st.sidebar.caption("Desenvolvido por Igor Cleto.")
