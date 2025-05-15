import streamlit as st

def local_css(file_name):
    """Loads a local CSS file into the Streamlit app."""
    try:
        with open(file_name, "r") as f: # Ensure read mode
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.error(f"CSS file not found: {file_name}. Please ensure the path is correct.")
    except Exception as e:
        st.error(f"Error loading CSS file {file_name}: {e}")
