"""Tests de l'interface Streamlit, sans navigateur, grâce à streamlit.testing (AppTest).

L'app tourne en mode démo : aucune donnée réelle ni appel à Notion ou Google Drive.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[2] / "app.py")
PASSWORD = "demo-pass"

pytestmark = pytest.mark.ui

CSV_HEADER = "date,nom,categorie,montant,description,compte\n"


@pytest.fixture
def demo_env(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "demo")
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    monkeypatch.delenv("DEMO_DATA_PATH", raising=False)


def start(clear_cache=True) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    if clear_cache:
        import streamlit as st

        st.cache_data.clear()
    return at.run()


def login(at: AppTest, password: str = PASSWORD) -> AppTest:
    return at.text_input(key="password").input(password).run()


def plotly_charts(at: AppTest):
    return at.get("plotly_chart")


def test_ecran_de_connexion(demo_env):
    at = start()
    assert not at.exception
    assert at.title[0].value == "Suivi Financier"
    assert at.text_input(key="password")
    assert not plotly_charts(at)


def test_mauvais_mot_de_passe(demo_env):
    at = login(start(), "faux")
    assert "Mot de passe incorrect" in at.error[0].value
    assert not plotly_charts(at)


def test_tableau_de_bord_complet(demo_env):
    at = login(start())
    assert not at.exception
    assert "Mode démo" in at.caption[0].value
    assert len(plotly_charts(at)) == 2
    assert len(at.dataframe) == 1
    assert at.dataframe[0].value.shape[0] > 0


def test_pas_de_bouton_recharger_en_demo(demo_env):
    at = login(start())
    assert not [b for b in at.sidebar.button if "Recharger" in b.label]


@pytest.mark.parametrize("periode", ["mois", "trimestre", "annee"])
@pytest.mark.parametrize("groupe", ["parent", "enfant"])
def test_toutes_les_combinaisons_de_vues(demo_env, periode, groupe):
    at = login(start())
    at.sidebar.selectbox[1].select(periode)
    at.sidebar.selectbox[3].select(groupe)
    at.sidebar.checkbox[0].check()  # lissage
    at.run()
    assert not at.exception
    assert len(plotly_charts(at)) == 2


def test_changement_de_compte(demo_env):
    at = login(start())
    perso = at.dataframe[0].value
    at.sidebar.selectbox[0].select("JOINT").run()
    joint = at.dataframe[0].value
    assert set(perso["compte"]) == {"PERSO"}
    assert set(joint["compte"]) == {"JOINT"}


def test_decocher_une_sous_categorie(demo_env):
    at = login(start())
    assert (at.dataframe[0].value["categorie"] == "Quotidien > Courses").any()
    at.checkbox(key="child_Quotidien_Courses").uncheck().run()
    assert not (at.dataframe[0].value["categorie"] == "Quotidien > Courses").any()


def test_periode_sans_depense(demo_env, monkeypatch, tmp_path):
    csv = tmp_path / "revenus.csv"
    csv.write_text(CSV_HEADER + "2026-01-01,Salaire,Revenus > Salaire,2000,,PERSO\n", encoding="utf-8")
    monkeypatch.setenv("DEMO_DATA_PATH", str(csv))
    at = login(start())
    assert any("Aucune dépense" in i.value for i in at.info)
    assert len(plotly_charts(at)) == 1


def test_aucune_transaction(demo_env, monkeypatch, tmp_path):
    csv = tmp_path / "vide.csv"
    csv.write_text(CSV_HEADER + "2026-01-01,Op,Quotidien > Courses,-10,,JOINT\n", encoding="utf-8")
    monkeypatch.setenv("DEMO_DATA_PATH", str(csv))
    at = login(start())
    assert any("Aucune transaction" in i.value for i in at.info)


def test_fichier_de_donnees_absent(demo_env, monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_DATA_PATH", str(tmp_path / "absent.csv"))
    at = login(start())
    assert not at.exception
    assert "Impossible de charger" in at.error[0].value
