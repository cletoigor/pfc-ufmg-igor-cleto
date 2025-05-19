import streamlit as st
import pandas as pd
import os # Keep os for general path operations if any are left, or for future use
from datetime import datetime, timedelta
import numpy as np # Keep for any direct numpy use, or if page functions need it passed explicitly

# Import refactored functions
from utils.data_helpers import load_data, get_available_devices, parse_cemig_bill, generate_report
from utils.ui_helpers import local_css
from utils.page_functions import show_resumo_casa, show_detalhes_dispositivo, show_analise_avancada, generate_2d_statistical_profile_plot, generate_3d_multichannel_profiles_plot

# --- Streamlit App UI ---
st.set_page_config(layout="wide", page_title="Análise de Energia Residencial")

STYLE_CSS_PATH = "style.css"
with open("style.css") as f:
    css = f.read()
st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

st.title("Análise de Consumo de Energia Residencial")

# --- Sidebar ---
st.sidebar.header("Navegação")
app_page = st.sidebar.radio(
    "Selecione uma Página",
    ["🏠 Resumo da Casa", "🔌 Detalhes por Dispositivo", "📊 Análise Avançada", "🧾 Analisar Conta CEMIG"] # Add "Analisar Conta CEMIG"
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
# Default period is "Últimos 7 Dias"
default_period_key = "Últimos 7 Dias"
selected_period_label = st.sidebar.selectbox(
    "Selecione o Período:",
    options=list(default_period_options.keys()),
    index=list(default_period_options.keys()).index(default_period_key) # Set default index
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
    # STAGING_DATA_PATH is now defined within data_helpers.py
    available_devices_list = get_available_devices(start_date_filter, end_date_filter)
else:
    st.sidebar.warning("Datas inválidas. Data inicial deve ser anterior ou igual à data final.")

selected_devices_list = []
if available_devices_list:
    default_selection = []
    if app_page == "🏠 Resumo da Casa":
        default_selection = available_devices_list  # Select all for Resumo da Casa
    else:
        if "Hack Sala" in available_devices_list:
            default_selection = ["Hack Sala"]
        elif available_devices_list: # Fallback if "Hack Sala" not present
            default_selection = [available_devices_list[0]] # Select the first available
        # If available_devices_list is empty, default_selection remains empty

    selected_devices_list = st.sidebar.multiselect(
        "Filtrar Dispositivos (Global)",
        options=available_devices_list,
        default=default_selection
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

# --- Page Routing ---
if app_page == "🏠 Resumo da Casa":
    show_resumo_casa(data_df, selected_devices_list, start_date_filter, end_date_filter)

elif app_page == "🔌 Detalhes por Dispositivo":
    selected_device_for_detail = None
    # For "Detalhes por Dispositivo", the selectbox should list all available devices,
    # but its default can be guided by the global filter if that makes sense, or just the first available.
    # If global filter (selected_devices_list) has "Hack Sala" and it's available, use it.
    # Otherwise, use the first from selected_devices_list if any, else first from available_devices_list.
    
    options_for_detail_selectbox = available_devices_list # Show all available for selection
    default_detail_device_index = 0

    if options_for_detail_selectbox: # Ensure there are options
        if "Hack Sala" in selected_devices_list and "Hack Sala" in options_for_detail_selectbox:
            default_detail_device_index = options_for_detail_selectbox.index("Hack Sala")
        elif selected_devices_list and selected_devices_list[0] in options_for_detail_selectbox:
            default_detail_device_index = options_for_detail_selectbox.index(selected_devices_list[0])
        # If no specific default, it will default to the first item (index 0)

        selected_device_for_detail = st.sidebar.selectbox(
            "Selecione um Dispositivo para Detalhes:",
            options=options_for_detail_selectbox,
            index=default_detail_device_index
        )
    show_detalhes_dispositivo(data_df, selected_device_for_detail, start_date_filter, end_date_filter)

elif app_page == "📊 Análise Avançada":
    # For "Análise Avançada", the CUSUM and Multichannel plots also have device selectors.
    # The global filter `selected_devices_list` will feed into these.
    show_analise_avancada(data_df, selected_devices_list, start_date_filter, end_date_filter)
    
    st.markdown("---")
    st.subheader("Perfil Estatístico Multicanal 2D (kWh)")
    
    # Device selection for the multichannel plot
    # Reuse selected_devices_list if not empty, otherwise use available_devices_list
    devices_for_multichannel_select = selected_devices_list if selected_devices_list else available_devices_list
    
    if devices_for_multichannel_select:
        multichannel_device = st.selectbox(
            "Selecione um dispositivo para os Perfis Multicanais:", 
            options=devices_for_multichannel_select, 
            key="multichannel_device_selector_combined" # Changed key to avoid conflict
        )
        if multichannel_device and not data_df.empty:
            device_specific_df_for_multichannel = data_df[data_df['device_name'] == multichannel_device]
            if not device_specific_df_for_multichannel.empty:
                # Generate and display 2D plot
                st.markdown("##### Perfil Estatístico 2D (Média Histórica, Desvios e Semana Atual)")
                help_text_2d = "Este gráfico 2D mostra a média histórica do consumo de energia (kWh) para cada hora da semana (168 canais), com bandas de desvio padrão. A linha da semana atual é sobreposta para comparação com o padrão histórico."
                st.subheader("Perfil Estatístico 2D", help=help_text_2d)
                fig_2d_profile = generate_2d_statistical_profile_plot(device_specific_df_for_multichannel, start_date_filter, end_date_filter)
                if fig_2d_profile.data:
                    st.plotly_chart(fig_2d_profile, use_container_width=True)
                else:
                    st.info(f"Não foi possível gerar o perfil estatístico 2D para '{multichannel_device}'. Verifique os dados.")

                st.markdown("---")
                # Generate and display 3D plot
                st.markdown("##### Perfis Semanais 3D (Média Histórica e Últimas Semanas Individuais)")
                help_text_3d = "Este gráfico 3D exibe a média histórica do consumo de energia (kWh) para cada hora da semana e os perfis individuais das últimas 4 semanas. Permite a visualização de tendências e desvios recentes em relação à média."
                st.subheader("Perfis Semanais 3D", help=help_text_3d)
                fig_3d_profiles, hist_avg_plotted = generate_3d_multichannel_profiles_plot(device_specific_df_for_multichannel, start_date_filter, end_date_filter)
                if fig_3d_profiles.data:
                    st.plotly_chart(fig_3d_profiles, use_container_width=True)
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

elif app_page == "🧾 Analisar Conta CEMIG":
    st.sidebar.header("Analisar Conta CEMIG")
    uploaded_file = st.sidebar.file_uploader("Upload da Conta CEMIG (PDF)", type=["pdf"])

    if uploaded_file is not None:
        try:
            # Save the uploaded file to a temporary location
            with open("temp.pdf", "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # Parse the bill with fixed password
            file_path = "temp.pdf"
            password = "0219"  # Senha fixa conforme especificado
            bill_data = parse_cemig_bill(file_path, password)

            # Generate and display the report
            generate_report(bill_data)

        except Exception as e:
            st.error(f"Erro ao processar o arquivo: {str(e)}")
        finally:
            # Clean up the temporary file
            if os.path.exists("temp.pdf"):
                os.remove("temp.pdf")

st.sidebar.markdown("---")
st.sidebar.caption("Desenvolvido por Igor Cleto.")
