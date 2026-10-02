"""Extraction des opérations bancaires via la CLI Woob."""

import json
import logging
import os
import subprocess
from typing import Any, Callable, Dict, List, Optional, TypedDict

logger = logging.getLogger(__name__)

COMPTES = ("PERSO", "JOINT")
WOOB_TIMEOUT_SECONDS = 120
WOOB_HISTORY_LIMIT = 30


class BankTransaction(TypedDict):
    date: str
    nom: str
    categorie: Optional[str]
    montant: float
    description: str
    id: str
    compte: str


def bank_ids() -> Dict[str, Optional[str]]:
    return {compte: os.getenv(f"BANK_{compte}_ID") for compte in COMPTES}


def raw_transaction_id(woob_id: str) -> str:
    return woob_id.split("@")[0]


def storage_transaction_id(compte: str, woob_id: str) -> str:
    """ID stocké dans Notion : `{compte}:{id}`, pour éviter les collisions entre comptes."""
    raw = raw_transaction_id(woob_id)
    prefix = f"{compte}:"
    return raw if raw.startswith(prefix) else f"{prefix}{raw}"


def is_existing_transaction(storage_id: str, existing_ids: set) -> bool:
    """Reconnaît aussi les IDs historiques, stockés sans préfixe de compte."""
    if storage_id in existing_ids:
        return True
    _, sep, raw = storage_id.partition(":")
    return bool(sep) and raw in existing_ids


def woob_executable(root: Optional[str] = None) -> str:
    root = root or os.path.dirname(os.path.abspath(__file__))
    for path in (
        os.path.join(root, ".venv", "Scripts", "woob.exe"),
        os.path.join(root, ".venv", "bin", "woob"),
    ):
        if os.path.isfile(path):
            return path
    return "woob"


def parse_woob_history(raw_json: str, compte: str) -> List[BankTransaction]:
    return [
        {
            "date": item["date"],
            "nom": item["label"],
            "categorie": item.get("category"),
            "montant": float(item["amount"]),
            "description": item.get("raw") or "",
            "id": storage_transaction_id(compte, item["id"]),
            "compte": compte,
        }
        for item in json.loads(raw_json)
    ]


def get_transactions_from_woob(
    run: Callable[..., Any] = subprocess.run,
) -> List[BankTransaction]:
    """Récupère l'historique de chaque compte. Un compte en échec n'empêche pas les autres."""
    exe = woob_executable()
    transactions: List[BankTransaction] = []

    for compte, bank_id in bank_ids().items():
        if not bank_id:
            logger.warning("BANK_%s_ID manquant, compte ignoré", compte)
            continue
        try:
            result = run(
                [exe, "bank", "history", bank_id, "-n", str(WOOB_HISTORY_LIMIT), "-f", "json"],
                capture_output=True,
                text=True,
                timeout=WOOB_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            logger.error("Woob : délai de %ss dépassé pour %s", WOOB_TIMEOUT_SECONDS, compte)
            continue
        except FileNotFoundError:
            logger.error("Woob : binaire introuvable (%s)", exe)
            continue

        if result.returncode != 0:
            logger.error("Woob : erreur pour %s : %s", compte, result.stderr)
            continue

        try:
            transactions.extend(parse_woob_history(result.stdout, compte))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.exception("Woob : sortie invalide pour %s", compte)

    return transactions
