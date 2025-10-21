import os
from dotenv import load_dotenv
import polars as pl
from datetime import datetime
import subprocess
import json
from notion_client import Client
from drive import load_from_drive, save_to_drive
import streamlit as st
from typing import List, Dict, Optional, Any

load_dotenv(override=True)
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
BANK_ID = {"PERSO": os.getenv("BANK_PERSO_ID"), "JOINT": os.getenv("BANK_JOINT_ID")}

if not NOTION_TOKEN or not NOTION_DATABASE_ID:
    raise ValueError("❌ Les variables d'environnement NOTION_TOKEN et NOTION_DATABASE_ID sont requises")

notion = Client(auth=NOTION_TOKEN)

def get_transactions_from_woob() -> List[Dict[str, Any]]:
    """Récupère les transactions depuis Woob.
    
    Returns:
        List[Dict[str, Any]]: Liste des transactions

    Debug: 
        rm ~/.config/woob/bank.storage
    """
    try:
        transactions = []
        for compte in ['PERSO', 'JOINT']:
            woob_path = os.path.join(os.path.dirname(__file__), ".venv/bin/woob")
            result = subprocess.run([
                woob_path, "bank", "history", BANK_ID[compte], "-n", "15", "-f", "json"
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            if result.returncode != 0:
                print(f"❌ Erreur Woob: {result.stderr}")
                return []

            raw_transactions = json.loads(result.stdout)
            transactions.extend(
                [
                    {
                        "date": t["date"],
                        "nom": t["label"],
                        "categorie": t["category"],
                        "montant": float(t["amount"]),
                        "description": t["raw"],
                        "id": t["id"].split("@")[0],
                        "compte": compte
                    }
                    for t in raw_transactions
                ]
            )
        return transactions

    except Exception as e:
        print(f"❌ Erreur lors de la récupération des transactions Woob: {str(e)}")
        return []

def get_existing_transaction_ids() -> set:
    """Récupère les IDs des transactions existantes dans Notion.
    
    Returns:
        set: Ensemble des IDs de transactions
    """
    existing_ids = set()
    has_more = True
    start_cursor = None

    while has_more:
        response = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            start_cursor=start_cursor if start_cursor else None
        )

        for page in response["results"]:
            prop = page["properties"].get("ID Transaction", {})
            rich_text = prop.get("rich_text", [])
            if rich_text:
                existing_ids.add(rich_text[0]["text"]["content"])

        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    return existing_ids

def send_transaction_to_notion(tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ajoute une transaction à la base Notion.
    
    Args:
        tx (Dict[str, Any]): La transaction à ajouter
        
    Returns:
        Optional[Dict[str, Any]]: La réponse de l'API Notion ou None en cas d'erreur
    """
    try:
        response = notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                "Date": {"date": {"start": tx["date"]}},
                "Nom": {"title": [{"text": {"content": tx["nom"]}}]},
                "Montant": {"number": tx["montant"]},
                "Description": {"rich_text": [{"text": {"content": tx["description"] if tx["description"] else ''}}]},
                "ID Transaction": {"rich_text": [{"text": {"content": tx["id"]}}]},
                "Compte": {"select": {"name": tx["compte"]}},
            }
        )
        return response
    except Exception as e:
        print(f"❌ Erreur lors de l'ajout de la transaction {tx.get('id')}: {str(e)}")
        return None

def send_transactions_to_notion(transactions: List[Dict[str, Any]]) -> Dict[str, int]:
    """Envoie les transactions à Notion.
    
    Args:
        transactions (List[Dict[str, Any]]): Liste des transactions à envoyer
        
    Returns:
        Dict[str, int]: Nombre de transactions ajoutées avec succès
    """
    existing_ids = get_existing_transaction_ids()
    print(f"🔎 {len(existing_ids)} transactions déjà présentes dans Notion.")

    new_transactions = [txn for txn in transactions if txn["id"] not in existing_ids]
    print(f"🆕 {len(new_transactions)} nouvelles transactions à ajouter.")

    success = 0
    for tx in new_transactions:
        if send_transaction_to_notion(tx):
            success += 1
    print(f"[Notion] {success}/{len(new_transactions)} transactions ajoutées")
    return {"success": success}

def load_transactions_from_csv() -> Optional[pl.DataFrame]:
    """Charge les transactions depuis le fichier CSV sur Google Drive.
    
    Returns:
        Optional[pl.DataFrame]: Le DataFrame des transactions ou None en cas d'erreur
    """
    try:
        df = load_from_drive("transactions.csv")
        if df is None:
            st.warning("⚠️ Aucun fichier CSV trouvé sur Google Drive")
            return None
        return df
    except Exception as e:
        st.error(f"❌ Erreur lors du chargement du CSV: {str(e)}")
        return None

def preprocess_transactions(transactions: List[Dict[str, Any]]) -> pl.DataFrame:
    """Prétraite les transactions pour l'affichage.
    
    Args:
        transactions (List[Dict[str, Any]]): Liste des transactions à prétraiter
        
    Returns:
        pl.DataFrame: DataFrame prétraité
    """
    df = pl.DataFrame(transactions)
    
    # Conversion de la date et création des colonnes temporelles
    df = df.with_columns([
        pl.col("date").str.strptime(pl.Date, "%Y-%m-%d").alias("date")
    ])

    df = df.with_columns([
        pl.col("date").dt.strftime("%Y-%m").alias("mois"),
        pl.concat_str([
            pl.col("date").dt.year().cast(pl.Utf8),
            pl.lit("-T"),
            pl.col("date").dt.quarter().cast(pl.Utf8)
        ]).alias("trimestre"),
        pl.col("date").dt.year().cast(pl.Utf8).alias("annee"),
        pl.col("categorie").str.split(" > ").list.first().alias("categorie-parent"),
        pl.col("categorie").str.split(" > ").list.last().alias("categorie-enfant")
    ])
    
    return df.sort("date", descending=True)

def get_transactions_from_notion(force_reload: bool = False) -> Optional[pl.DataFrame]:
    """Récupère les transactions depuis Notion ou le CSV sur Google Drive.
    
    Args:
        force_reload (bool): Force le rechargement depuis Notion
        
    Returns:
        Optional[pl.DataFrame]: Le DataFrame des transactions ou None en cas d'erreur
    """
    # Vérification du CSV si pas de rechargement forcé
    if not force_reload:
        return load_transactions_from_csv()

    # Récupération depuis Notion
    transactions = []
    has_more = True
    start_cursor = None

    while has_more:
        response = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            start_cursor=start_cursor
        )

        for page in response["results"]:
            props = page["properties"]
            transactions.append({
                "date": props["Date"]["date"]["start"],
                "nom": props["Nom"]["title"][0]["text"]["content"],
                "categorie": props["Catégorie"]["select"]["name"] if props["Catégorie"]["select"] else None,
                "montant": props["Montant"]["number"],
                "description": props["Description"]["rich_text"][0]["text"]["content"],
                "compte": props["Compte"]["select"]["name"]
            })

        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    df = preprocess_transactions(transactions)
    save_to_drive(df, "transactions.csv")
    
    return df


if __name__ == "__main__":
    print(f"📅 {datetime.now().strftime('%Y-%m-%d')}")
    transactions = get_transactions_from_woob()
    send_transactions_to_notion(transactions)
    print()
