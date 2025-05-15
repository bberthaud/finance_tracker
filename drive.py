from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
import os
import io
import polars as pl
import streamlit as st
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)
SCOPES = ['https://www.googleapis.com/auth/drive.file']
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")

if not DRIVE_FOLDER_ID:
    raise ValueError("❌ La variable d'environnement DRIVE_FOLDER_ID est requise")

def get_google_drive_service():
    """Initialise et retourne le service Google Drive.
    
    Returns:
        Optional[build]: Le service Google Drive ou None en cas d'erreur.
    """
    try:
        credentials = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=SCOPES
        )
        return build('drive', 'v3', credentials=credentials)
    except KeyError:
        st.error("❌ Les identifiants Google Drive ne sont pas configurés dans les secrets Streamlit")
        return None
    except Exception as e:
        st.error(f"❌ Erreur lors de l'authentification Google Drive: {str(e)}")
        return None

def save_to_drive(df: pl.DataFrame, file_name: str) -> Optional[str]:
    """Sauvegarde un DataFrame Polars sur Google Drive.
    
    Args:
        df (pl.DataFrame): Le DataFrame à sauvegarder
        file_name (str): Le nom du fichier à créer/mettre à jour
        
    Returns:
        Optional[str]: L'ID du fichier sauvegardé ou None en cas d'erreur
    """
    service = get_google_drive_service()
    if service is None:
        return None
    
    try:
        # Convertit le DataFrame en CSV dans un buffer mémoire
        buffer = io.BytesIO()
        df.write_csv(buffer)
        buffer.seek(0)
        
        # Vérifie si le fichier existe déjà
        results = service.files().list(
            q=f"name='{file_name}' and '{DRIVE_FOLDER_ID}' in parents",
            spaces='drive',
            fields='files(id)'
        ).execute()
        items = results.get('files', [])
        
        file_metadata = {
            'name': file_name,
            'parents': [DRIVE_FOLDER_ID]
        }
        media = MediaIoBaseUpload(buffer, mimetype='text/csv', resumable=True)
        
        if items:
            # Met à jour le fichier existant
            file_id = items[0]['id']
            file = service.files().update(
                fileId=file_id,
                media_body=media
            ).execute()
        else:
            # Crée un nouveau fichier
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
        
        file_id = file.get('id')
        file_url = f"https://drive.google.com/file/d/{file_id}/view"
        
        # Crée un conteneur pour le message
        if 'drive_message' not in st.session_state:
            st.session_state.drive_message = st.empty()
        
        # Affiche le message dans le conteneur
        st.session_state.drive_message.success(
            f"✅ Fichier sauvegardé : [Ouvrir dans Drive]({file_url})",
            icon="💾"
        )
        
        return file_id
    except Exception as e:
        st.error(f"❌ Erreur lors de la sauvegarde sur Google Drive: {str(e)}")
        return None

def load_from_drive(file_name: str) -> Optional[pl.DataFrame]:
    """Charge un fichier depuis Google Drive.
    
    Args:
        file_name (str): Le nom du fichier à charger
        
    Returns:
        Optional[pl.DataFrame]: Le DataFrame chargé ou None en cas d'erreur
    """
    service = get_google_drive_service()
    if service is None:
        return None
    
    try:
        results = service.files().list(
            q=f"name='{file_name}' and '{DRIVE_FOLDER_ID}' in parents",
            spaces='drive',
            fields='files(id)'
        ).execute()
        items = results.get('files', [])
        
        if not items:
            st.warning(f"⚠️ Aucun fichier '{file_name}' trouvé dans le dossier Drive")
            return None
        
        file_id = items[0]['id']
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        fh.seek(0)
        return pl.read_csv(fh)
    except Exception as e:
        st.error(f"❌ Erreur lors du chargement depuis Google Drive: {str(e)}")
        return None 