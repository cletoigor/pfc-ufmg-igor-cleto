import streamlit as st
import pandas as pd
import os # Keep os for general path operations if any are left, or for future use
from datetime import datetime, timedelta
import numpy as np # Keep for any direct numpy use, or if page functions need it passed explicitly

# Import refactored functions
from utils.data_helpers import load_data, get_available_devices, parse_cemig_bill, generate_report
from utils.ui_helpers import local_css
from utils.page_functions import show_resumo_casa, show_detalhes_dispositivo, show_analise_avancada

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
    # STAGING_DATA_PATH is now defined within data_helpers.py
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
    # STAGING_DATA_PATH is now defined within data_helpers.py
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
    if available_devices_list: 
        default_device_for_detail = selected_devices_list[0] if len(selected_devices_list) == 1 else None
        if not available_devices_list and default_device_for_detail: 
             default_device_for_detail = None
        
        current_index = 0 # Default to first item
        if default_device_for_detail and default_device_for_detail in available_devices_list:
            current_index = available_devices_list.index(default_device_for_detail)
        elif selected_devices_list and selected_devices_list[0] in available_devices_list: # Fallback to first of global selection
            current_index = available_devices_list.index(selected_devices_list[0])


        selected_device_for_detail = st.sidebar.selectbox(
            "Selecione um Dispositivo para Detalhes:",
            options=available_devices_list, # options must be from available devices
            index=current_index 
        )
    show_detalhes_dispositivo(data_df, selected_device_for_detail, start_date_filter, end_date_filter)
elif app_page == "📊 Análise Avançada": 
    show_analise_avancada(data_df, selected_devices_list, start_date_filter, end_date_filter)
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
