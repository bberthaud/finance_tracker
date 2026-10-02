import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from processing import preprocess_transactions

FIXTURES = Path(__file__).parent / "fixtures"


def tx(date, categorie, montant, compte="PERSO", nom="op"):
    return {
        "date": date,
        "nom": nom,
        "categorie": categorie,
        "montant": montant,
        "description": "",
        "compte": compte,
    }


@pytest.fixture
def sample_df():
    """Petit jeu couvrant : 2 trimestres, revenus, remboursement, sans catégorie, 2 comptes."""
    return preprocess_transactions(
        [
            tx("2026-01-05", "Revenus > Salaire", 2000.0),
            tx("2026-01-10", "Quotidien > Courses", -100.0),
            tx("2026-01-20", "Loisirs > Cinéma", -20.0),
            tx("2026-02-05", "Revenus > Salaire", 2000.0),
            tx("2026-02-12", "Quotidien > Courses", -150.0),
            tx("2026-02-15", "Santé > Pharmacie", -30.0),
            tx("2026-02-20", "Santé > Pharmacie", 50.0),
            tx("2026-02-25", None, -10.0),
            tx("2026-04-03", "Quotidien > Boulangerie", -12.0),
            tx("2026-01-15", "Quotidien > Courses", -999.0, compte="JOINT"),
        ]
    )


@pytest.fixture
def notion_pages():
    return json.loads((FIXTURES / "notion_pages.json").read_text(encoding="utf-8"))


@pytest.fixture
def woob_history_json():
    return (FIXTURES / "woob_history.json").read_text(encoding="utf-8")


class FakeNotionClient:
    """Imite le sous-ensemble de notion_client.Client utilisé par l'app, avec pagination."""

    def __init__(self, pages, page_size=2, create_errors=None):
        self._pages = pages
        self._page_size = page_size
        self._create_errors = list(create_errors or [])
        self.created = []
        self.queries = []
        self.databases = SimpleNamespace(query=self._query, retrieve=self._retrieve)
        self.pages = SimpleNamespace(create=self._create)

    def _retrieve(self, database_id):
        return {"properties": {"ID Transaction": {"id": "abc%3D"}}}

    def _query(self, database_id, start_cursor=None, **kwargs):
        self.queries.append({"start_cursor": start_cursor, **kwargs})
        start = int(start_cursor or 0)
        end = start + self._page_size
        return {
            "results": self._pages[start:end],
            "has_more": end < len(self._pages),
            "next_cursor": str(end) if end < len(self._pages) else None,
        }

    def _create(self, parent, properties):
        if self._create_errors:
            raise self._create_errors.pop(0)
        self.created.append(properties)
        return {"id": f"new-{len(self.created)}"}


class FakeApiError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


@pytest.fixture
def notion_env(monkeypatch):
    monkeypatch.setenv("NOTION_DATABASE_ID", "db-test")
    monkeypatch.setenv("NOTION_TOKEN", "secret-test")
