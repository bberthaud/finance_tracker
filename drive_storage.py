from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
import os
import io
import polars as pl
import streamlit as st

SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_google_drive_service():
    """Initialise et retourne le service Google Drive"""
    try:
        credentials = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=SCOPES
        )
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        st.error(f"Erreur lors de l'authentification Google Drive: {e}")
        return None

def save_to_drive(df, file_name):
    """Sauvegarde un DataFrame Polars sur Google Drive"""
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
            q=f"name='{file_name}' and '1LC8KV5jX1rVAI3mptb0zigGWs7fHh03u' in parents",
            spaces='drive',
            fields='files(id)'
        ).execute()
        items = results.get('files', [])
        
        file_metadata = {
            'name': file_name,
            'parents': ['1LC8KV5jX1rVAI3mptb0zigGWs7fHh03u']
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
        st.success(f"✅ Fichier sauvegardé : [Ouvrir dans Drive]({file_url})")
        return file_id
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde sur Google Drive: {e}")
        return None

def load_from_drive(file_name):
    """Charge un fichier depuis Google Drive"""
    service = get_google_drive_service()
    if service is None:
        return None
    
    try:
        results = service.files().list(
            q=f"name='{file_name}'",
            spaces='drive',
            fields='files(id)'
        ).execute()
        items = results.get('files', [])
        
        if not items:
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
        st.error(f"Erreur lors du chargement depuis Google Drive: {e}")
        return None 