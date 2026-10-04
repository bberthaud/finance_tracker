"""Tests de l'interface Streamlit, sans navigateur, grâce à streamlit.testing (AppTest).

L'app tourne en mode démo : aucune donnée réelle ni appel à Notion ou Google Drive.
"""

import json
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


def chart_spec(chart) -> dict:
    return json.loads(chart.proto.spec)


def test_ecran_de_connexion(demo_env):
    at = start()
    assert not at.exception
    assert at.title[0].value == "Suivi Financier"
    assert at.text_input(key="password")
    assert [t.key for t in at.sidebar.toggle] == ["masquer_montants"]
    assert at.sidebar.toggle[0].value is False
    assert len(at.sidebar.children) == 1
    assert not at.main.toggle
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


def test_interrupteur_en_tete_de_sidebar_apres_connexion(demo_env):
    at = login(start())
    assert len(at.toggle) == 1
    assert at.sidebar.children[0].key == "masquer_montants"


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


def category_checkboxes(at: AppTest):
    return [c for c in at.sidebar.checkbox if c.key and c.key.startswith(("parent_", "child_"))]


def test_tout_deselectionner_puis_tout_selectionner(demo_env):
    at = login(start())
    assert any(c.value for c in category_checkboxes(at))

    at.sidebar.button(key="unselect_all").click().run()
    assert not at.exception
    assert not at.warning
    assert not any(c.value for c in category_checkboxes(at))
    if at.dataframe:
        assert set(at.dataframe[0].value["categorie"].fillna("")) <= {""}

    at.sidebar.button(key="select_all").click().run()
    assert all(c.value for c in category_checkboxes(at))


def test_cocher_parent_coche_ses_enfants(demo_env):
    at = login(start())
    exclus_children = [c for c in category_checkboxes(at) if c.key.startswith("child_Exclus_")]
    assert exclus_children
    assert not at.checkbox(key="parent_Exclus").value
    assert all(not c.value for c in exclus_children)

    at.checkbox(key="parent_Exclus").check().run()
    assert not at.exception
    assert at.checkbox(key="parent_Exclus").value
    assert all(c.value for c in category_checkboxes(at) if c.key.startswith("child_Exclus_"))


def test_decocher_parent_decoche_ses_enfants(demo_env):
    at = login(start())
    quotidien_children = [c for c in category_checkboxes(at) if c.key.startswith("child_Quotidien_")]
    assert quotidien_children
    assert at.checkbox(key="parent_Quotidien").value
    assert all(c.value for c in quotidien_children)

    at.checkbox(key="parent_Quotidien").uncheck().run()
    assert not at.exception
    assert not at.checkbox(key="parent_Quotidien").value
    assert all(not c.value for c in category_checkboxes(at) if c.key.startswith("child_Quotidien_"))


def test_categories_exclues_par_defaut(demo_env):
    at = login(start())
    assert at.checkbox(key="parent_Quotidien").value
    assert not at.checkbox(key="parent_Taxes").value
    assert all(not c.value for c in category_checkboxes(at) if c.key.startswith("child_Taxes_"))


def test_masquer_les_montants_des_la_connexion(demo_env):
    at = start()
    at.toggle(key="masquer_montants").set_value(True).run()
    at = login(at)
    assert not at.exception
    assert at.toggle(key="masquer_montants").value is True

    bar, pie = (chart_spec(c) for c in plotly_charts(at))
    assert bar["layout"]["yaxis"]["showticklabels"] is False
    for trace in bar["data"] + pie["data"]:
        assert "%{y" not in trace["hovertemplate"] and "%{value" not in trace["hovertemplate"]
        assert "customdata" not in trace
    assert pie["layout"]["annotations"][0]["text"] == "••• €"
    assert set(at.dataframe[0].value["montant"]) == {"••• €"}

    at.toggle(key="masquer_montants").set_value(False).run()
    bar = chart_spec(plotly_charts(at)[0])
    assert bar["layout"]["yaxis"]["showticklabels"] is True
    assert at.dataframe[0].value["montant"].dtype.kind == "f"


def test_periode_sans_depense(demo_env, monkeypatch, tmp_path):
    csv = tmp_path / "revenus.csv"
    csv.write_text(CSV_HEADER + "2026-01-01,Salaire,Revenus > Salaire,2000,,PERSO\n", encoding="utf-8")
    monkeypatch.setenv("DEMO_DATA_PATH", str(csv))
    at = login(start())
    assert not any("Aucune dépense" in i.value for i in at.info)
    bar, placeholder = (chart_spec(c) for c in plotly_charts(at))
    assert placeholder["data"] == []
    assert placeholder["layout"]["height"] == bar["layout"]["height"]
    [message] = placeholder["layout"]["annotations"]
    assert message["text"] == "Aucune dépense à afficher pour cette période."
    assert (message["x"], message["y"], message["xref"], message["yref"]) == (0.5, 0.5, "paper", "paper")


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
