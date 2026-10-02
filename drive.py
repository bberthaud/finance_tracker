"""Client Google Drive sans dépendance Streamlit."""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import polars as pl
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TRANSACTIONS_CSV = "transactions.csv"


@dataclass
class DriveOutcome:
    status: str  # success | error | warning
    message: str
    icon: str
    file_id: Optional[str] = None
    df: Optional[pl.DataFrame] = None


def drive_folder_id() -> str:
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if not folder_id:
        raise ValueError("La variable d'environnement DRIVE_FOLDER_ID est requise")
    return folder_id


def build_drive_service(credentials_info: dict) -> Any:
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=credentials)


def _escape_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_file_id(service: Any, file_name: str, folder_id: str) -> Optional[str]:
    query = f"name='{_escape_query_value(file_name)}' and '{_escape_query_value(folder_id)}' in parents"
    results = service.files().list(q=query, spaces="drive", fields="files(id)").execute()
    items = results.get("files", [])
    return items[0]["id"] if items else None


def save_to_drive(
    service: Any,
    df: pl.DataFrame,
    file_name: str = TRANSACTIONS_CSV,
    folder_id: Optional[str] = None,
) -> DriveOutcome:
    try:
        folder_id = folder_id or drive_folder_id()
        buffer = io.BytesIO()
        df.write_csv(buffer)
        buffer.seek(0)

        existing_id = find_file_id(service, file_name, folder_id)
        media = MediaIoBaseUpload(buffer, mimetype="text/csv", resumable=True)

        if existing_id:
            file = service.files().update(fileId=existing_id, media_body=media).execute()
        else:
            file = (
                service.files()
                .create(
                    body={"name": file_name, "parents": [folder_id]},
                    media_body=media,
                    fields="id",
                )
                .execute()
            )

        file_id = file.get("id") or existing_id
        file_url = f"https://drive.google.com/file/d/{file_id}/view"
        return DriveOutcome(
            status="success",
            message=f"Fichier sauvegardé : [Ouvrir dans Drive]({file_url})",
            icon="💾",
            file_id=file_id,
        )
    except Exception as exc:
        logger.exception("Erreur sauvegarde Drive")
        return DriveOutcome(
            status="error",
            message=f"Erreur lors de la sauvegarde sur Google Drive: {exc}",
            icon="❌",
        )


def load_from_drive(
    service: Any,
    file_name: str = TRANSACTIONS_CSV,
    folder_id: Optional[str] = None,
) -> DriveOutcome:
    try:
        folder_id = folder_id or drive_folder_id()
        file_id = find_file_id(service, file_name, folder_id)
        if not file_id:
            return DriveOutcome(
                status="warning",
                message=f"Aucun fichier '{file_name}' trouvé dans le dossier Drive",
                icon="⚠️",
            )

        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        fh.seek(0)
        return DriveOutcome(
            status="success",
            message="",
            icon="💾",
            file_id=file_id,
            df=pl.read_csv(fh),
        )
    except Exception as exc:
        logger.exception("Erreur chargement Drive")
        return DriveOutcome(
            status="error",
            message=f"Erreur lors du chargement depuis Google Drive: {exc}",
            icon="❌",
        )
