"""Accès à la base Notion des transactions, et script de synchro banque → Notion (cron)."""

import logging
import os
import sys
import time
from functools import lru_cache
from typing import Any, Callable, Dict, Iterator, List, Optional, Set

import polars as pl

from bank import BankTransaction, get_transactions_from_woob, is_existing_transaction
from processing import Transaction, preprocess_transactions

logger = logging.getLogger("notion")

NOTION_CREATE_RETRIES = 3
TRANSIENT_HTTP_STATUSES = {409, 429, 500, 502, 503, 504}


def notion_database_id() -> str:
    database_id = os.getenv("NOTION_DATABASE_ID")
    if not database_id:
        raise ValueError("La variable d'environnement NOTION_DATABASE_ID est requise")
    return database_id


@lru_cache(maxsize=1)
def get_notion_client() -> Any:
    from notion_client import Client

    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("La variable d'environnement NOTION_TOKEN est requise")
    return Client(auth=token)


def get_title(prop: Optional[dict]) -> str:
    return _first_text((prop or {}).get("title"))


def get_rich_text(prop: Optional[dict]) -> str:
    return _first_text((prop or {}).get("rich_text"))


def _first_text(items: Optional[list]) -> str:
    if not items:
        return ""
    first = items[0]
    return first.get("plain_text") or (first.get("text") or {}).get("content") or ""


def get_select(prop: Optional[dict]) -> Optional[str]:
    sel = (prop or {}).get("select")
    return sel.get("name") if sel else None


def get_date_start(prop: Optional[dict]) -> Optional[str]:
    date = (prop or {}).get("date")
    return date.get("start") if date else None


def get_number(prop: Optional[dict]) -> Optional[float]:
    return (prop or {}).get("number")


def page_to_transaction(props: dict) -> Optional[Transaction]:
    date = get_date_start(props.get("Date"))
    if not date:
        return None
    return {
        "date": date[:10],
        "nom": get_title(props.get("Nom")),
        "categorie": get_select(props.get("Catégorie")),
        "montant": get_number(props.get("Montant")),
        "description": get_rich_text(props.get("Description")),
        "compte": get_select(props.get("Compte")),
    }


def iter_pages(client: Any, database_id: str, **query: Any) -> Iterator[dict]:
    """Parcourt toutes les pages d'une base, en suivant la pagination."""
    start_cursor = None
    while True:
        response = client.databases.query(database_id=database_id, start_cursor=start_cursor, **query)
        yield from response["results"]
        if not response.get("has_more"):
            return
        start_cursor = response.get("next_cursor")


def fetch_transactions_from_notion(client: Any = None) -> pl.DataFrame:
    client = client or get_notion_client()
    rows = [page_to_transaction(page["properties"]) for page in iter_pages(client, notion_database_id())]
    return preprocess_transactions([row for row in rows if row])


def _id_property_filter(client: Any, database_id: str) -> Dict[str, Any]:
    """Ne demander que la propriété « ID Transaction » quand son identifiant est connu."""
    try:
        prop = client.databases.retrieve(database_id=database_id)["properties"]["ID Transaction"]
        return {"filter_properties": [prop["id"]]}
    except Exception:
        logger.warning("Propriété « ID Transaction » introuvable, lecture complète des pages")
        return {}


def get_existing_transaction_ids(client: Any = None) -> Set[str]:
    client = client or get_notion_client()
    database_id = notion_database_id()
    query = _id_property_filter(client, database_id)
    ids = (
        get_rich_text(page["properties"].get("ID Transaction"))
        for page in iter_pages(client, database_id, **query)
    )
    return {i for i in ids if i}


def is_transient_error(exc: Exception) -> bool:
    status = getattr(exc, "status", None)
    if status is not None:
        return status in TRANSIENT_HTTP_STATUSES
    return type(exc).__name__ in {"RequestTimeoutError", "HTTPError", "ConnectError", "TimeoutException"}


def transaction_properties(tx: BankTransaction) -> Dict[str, Any]:
    return {
        "Date": {"date": {"start": tx["date"]}},
        "Nom": {"title": [{"text": {"content": tx["nom"] or ""}}]},
        "Montant": {"number": tx["montant"]},
        "Description": {"rich_text": [{"text": {"content": tx.get("description") or ""}}]},
        "ID Transaction": {"rich_text": [{"text": {"content": tx["id"]}}]},
        "Compte": {"select": {"name": tx["compte"]}},
    }


def send_transaction_to_notion(
    tx: BankTransaction,
    client: Any = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[dict]:
    """Crée la page ; seules les erreurs temporaires (429, 5xx, réseau) sont retentées."""
    client = client or get_notion_client()
    database_id = notion_database_id()
    for attempt in range(1, NOTION_CREATE_RETRIES + 1):
        try:
            return client.pages.create(
                parent={"database_id": database_id}, properties=transaction_properties(tx)
            )
        except Exception as exc:
            if not is_transient_error(exc) or attempt == NOTION_CREATE_RETRIES:
                logger.error("Notion : échec de création id=%s : %s", tx.get("id"), exc)
                return None
            logger.warning(
                "Notion : essai %s/%s échoué id=%s : %s", attempt, NOTION_CREATE_RETRIES, tx.get("id"), exc
            )
            sleep(2 ** (attempt - 1))
    return None


def send_transactions_to_notion(
    transactions: List[BankTransaction],
    client: Any = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, int]:
    client = client or get_notion_client()
    existing_ids = get_existing_transaction_ids(client)
    base = len(existing_ids)

    new = [tx for tx in transactions if not is_existing_transaction(tx["id"], existing_ids)]
    success = sum(1 for tx in new if send_transaction_to_notion(tx, client, sleep))
    failed = len(new) - success
    skipped = len(transactions) - len(new)
    logger.info(
        "Notion %s ajoutée(s), %s échec(s), %s déjà présente(s) (base=%s)",
        success,
        failed,
        skipped,
        base,
    )
    return {"success": success, "failed": failed, "skipped": skipped, "base": base}


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(override=True)
    configure_logging()
    sync_logger = logging.getLogger("sync")
    sync_logger.info("début")
    transactions = get_transactions_from_woob()
    result = send_transactions_to_notion(transactions)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
