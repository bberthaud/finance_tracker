import pytest

import notion
from tests.conftest import FakeApiError, FakeNotionClient


class TestLectureProprietes:
    def test_champs_vides(self):
        assert notion.get_title({"title": []}) == ""
        assert notion.get_rich_text(None) == ""
        assert notion.get_select({"select": None}) is None
        assert notion.get_date_start({"date": None}) is None
        assert notion.get_number({}) is None

    def test_plain_text_prioritaire(self):
        prop = {"title": [{"plain_text": "Affiché", "text": {"content": "brut"}}]}
        assert notion.get_title(prop) == "Affiché"

    def test_page_complete(self, notion_pages):
        assert notion.page_to_transaction(notion_pages[0]["properties"]) == {
            "date": "2026-09-14",
            "nom": "Carrefour",
            "categorie": "Quotidien > Courses",
            "montant": -54.2,
            "description": "CB CARREFOUR",
            "compte": "PERSO",
        }

    def test_page_aux_champs_vides(self, notion_pages):
        row = notion.page_to_transaction(notion_pages[1]["properties"])
        assert row["date"] == "2026-09-01"  # heure et fuseau retirés
        assert row["nom"] == ""
        assert row["categorie"] is None

    def test_page_sans_date_ignoree(self, notion_pages):
        assert notion.page_to_transaction(notion_pages[2]["properties"]) is None


class TestLectureBase:
    def test_pagination_complete(self, notion_env, notion_pages):
        client = FakeNotionClient(notion_pages, page_size=1)
        df = notion.fetch_transactions_from_notion(client)
        assert df.height == 2  # la page sans date est écartée
        assert len(client.queries) == 3

    def test_ids_existants_avec_filtre_de_propriete(self, notion_env, notion_pages):
        client = FakeNotionClient(notion_pages)
        assert notion.get_existing_transaction_ids(client) == {"PERSO:a1b2c3", "legacy123"}
        assert client.queries[0]["filter_properties"] == ["abc%3D"]

    def test_variable_manquante(self, monkeypatch, notion_pages):
        monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
        with pytest.raises(ValueError, match="NOTION_DATABASE_ID"):
            notion.fetch_transactions_from_notion(FakeNotionClient(notion_pages))


def bank_tx(id_, compte="PERSO"):
    return {
        "date": "2026-09-20",
        "nom": "op",
        "categorie": None,
        "montant": -1.0,
        "description": "",
        "id": id_,
        "compte": compte,
    }


class TestEcriture:
    def test_erreur_temporaire_retentee(self, notion_env):
        client = FakeNotionClient([], create_errors=[FakeApiError(429), FakeApiError(503)])
        sleeps = []
        assert notion.send_transaction_to_notion(bank_tx("PERSO:x"), client, sleeps.append)
        assert sleeps == [1, 2]

    def test_erreur_definitive_non_retentee(self, notion_env):
        client = FakeNotionClient([], create_errors=[FakeApiError(400)])
        sleeps = []
        assert notion.send_transaction_to_notion(bank_tx("PERSO:x"), client, sleeps.append) is None
        assert sleeps == []

    def test_pas_d_attente_apres_le_dernier_essai(self, notion_env):
        client = FakeNotionClient([], create_errors=[FakeApiError(500)] * 3)
        sleeps = []
        assert notion.send_transaction_to_notion(bank_tx("PERSO:x"), client, sleeps.append) is None
        assert sleeps == [1, 2]

    def test_proprietes_envoyees(self):
        props = notion.transaction_properties(bank_tx("PERSO:x"))
        assert props["ID Transaction"]["rich_text"][0]["text"]["content"] == "PERSO:x"
        assert props["Compte"]["select"]["name"] == "PERSO"


class TestSynchro:
    def test_seules_les_nouvelles_transactions_sont_creees(self, notion_env, notion_pages):
        client = FakeNotionClient(notion_pages)
        result = notion.send_transactions_to_notion(
            [bank_tx("PERSO:a1b2c3"), bank_tx("PERSO:legacy123"), bank_tx("JOINT:nouveau", "JOINT")],
            client,
            sleep=lambda s: None,
        )
        assert result == {"success": 1, "failed": 0, "skipped": 2}
        created_ids = [p["ID Transaction"]["rich_text"][0]["text"]["content"] for p in client.created]
        assert created_ids == ["JOINT:nouveau"]

    def test_code_retour_du_script(self, monkeypatch, notion_env):
        monkeypatch.setattr(notion, "get_transactions_from_woob", lambda: [bank_tx("PERSO:z")])
        monkeypatch.setattr(
            notion,
            "send_transactions_to_notion",
            lambda txs: {"success": 0, "failed": 1, "skipped": 0},
        )
        assert notion.main() == 1
