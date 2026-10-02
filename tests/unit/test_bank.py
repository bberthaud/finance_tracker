import subprocess
from types import SimpleNamespace

import pytest

import bank


@pytest.fixture
def comptes(monkeypatch):
    monkeypatch.setenv("BANK_PERSO_ID", "perso@cragr")
    monkeypatch.setenv("BANK_JOINT_ID", "joint@cragr")


def completed(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


class TestIdentifiants:
    def test_prefixe_par_compte(self):
        assert bank.storage_transaction_id("PERSO", "abc@cragr") == "PERSO:abc"

    def test_prefixe_idempotent(self):
        assert bank.storage_transaction_id("PERSO", "PERSO:abc") == "PERSO:abc"

    @pytest.mark.parametrize(
        ("storage_id", "existants", "attendu"),
        [
            ("PERSO:abc", {"PERSO:abc"}, True),
            ("PERSO:abc", {"abc"}, True),  # ID historique sans préfixe
            ("PERSO:abc", {"JOINT:xyz"}, False),
            ("abc", {"abc"}, True),
        ],
    )
    def test_deduplication(self, storage_id, existants, attendu):
        assert bank.is_existing_transaction(storage_id, existants) is attendu


class TestParsing:
    def test_sortie_woob(self, woob_history_json):
        txs = bank.parse_woob_history(woob_history_json, "PERSO")
        assert txs[0] == {
            "date": "2026-09-14",
            "nom": "CARREFOUR MARKET",
            "categorie": "Quotidien > Courses",
            "montant": -54.2,
            "description": "CB CARREFOUR MARKET 13/09",
            "id": "PERSO:a1b2c3",
            "compte": "PERSO",
        }
        assert txs[1]["description"] == ""
        assert txs[1]["categorie"] is None


class TestExecutable:
    def test_venv_linux(self, tmp_path):
        exe = tmp_path / ".venv" / "bin" / "woob"
        exe.parent.mkdir(parents=True)
        exe.touch()
        assert bank.woob_executable(str(tmp_path)) == str(exe)

    def test_repli_sur_le_path(self, tmp_path):
        assert bank.woob_executable(str(tmp_path)) == "woob"


class TestRecuperation:
    def test_deux_comptes(self, comptes, woob_history_json):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return completed(woob_history_json)

        txs = bank.get_transactions_from_woob(run=fake_run)
        assert len(txs) == 4
        assert {t["compte"] for t in txs} == {"PERSO", "JOINT"}
        assert all(kw["timeout"] == bank.WOOB_TIMEOUT_SECONDS for _, kw in calls)

    def test_un_compte_en_echec_n_annule_pas_l_autre(self, comptes, woob_history_json, caplog):
        def fake_run(cmd, **kwargs):
            if "perso@cragr" in cmd:
                return completed(returncode=1, stderr="auth failed")
            return completed(woob_history_json)

        txs = bank.get_transactions_from_woob(run=fake_run)
        assert {t["compte"] for t in txs} == {"JOINT"}
        assert "auth failed" in caplog.text

    def test_delai_depasse(self, comptes, woob_history_json):
        def fake_run(cmd, **kwargs):
            if "perso@cragr" in cmd:
                raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
            return completed(woob_history_json)

        assert {t["compte"] for t in bank.get_transactions_from_woob(run=fake_run)} == {"JOINT"}

    def test_json_invalide(self, comptes):
        assert bank.get_transactions_from_woob(run=lambda cmd, **kw: completed("pas du json")) == []

    def test_compte_non_configure(self, monkeypatch, woob_history_json):
        monkeypatch.setenv("BANK_PERSO_ID", "perso@cragr")
        monkeypatch.delenv("BANK_JOINT_ID", raising=False)
        txs = bank.get_transactions_from_woob(run=lambda cmd, **kw: completed(woob_history_json))
        assert {t["compte"] for t in txs} == {"PERSO"}

    def test_binaire_introuvable(self, comptes):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        assert bank.get_transactions_from_woob(run=fake_run) == []
