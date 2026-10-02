from datetime import date

import polars as pl
import pytest

from processing import (
    DEFAULT_PIE_COLOR,
    category_structure,
    compute_pie_data,
    compute_totals,
    enfant_parent_map,
    filter_by_categories,
    pie_colors_for_labels,
    preprocess_transactions,
    preprocess_transactions_df,
    smoothing_divisor,
)


class TestPreprocess:
    def test_derive_periodes_et_categories(self, sample_df):
        row = sample_df.filter(pl.col("date") == date(2026, 4, 3)).row(0, named=True)
        assert row["mois"] == "2026-04"
        assert row["trimestre"] == "2026-T2"
        assert row["annee"] == "2026"
        assert row["categorie-parent"] == "Quotidien"
        assert row["categorie-enfant"] == "Boulangerie"

    def test_tri_par_date_decroissante(self, sample_df):
        dates = sample_df["date"].to_list()
        assert dates == sorted(dates, reverse=True)

    def test_categorie_absente_devient_vide(self, sample_df):
        row = sample_df.filter(pl.col("montant") == -10.0).row(0, named=True)
        assert row["categorie-parent"] == ""
        assert row["categorie-enfant"] == ""

    def test_categorie_sans_sous_niveau(self):
        df = preprocess_transactions(
            [
                {
                    "date": "2026-01-01",
                    "nom": "x",
                    "categorie": "Revenus",
                    "montant": 1.0,
                    "description": "",
                    "compte": "PERSO",
                }
            ]
        )
        assert df.row(0, named=True)["categorie-enfant"] == "Revenus"

    def test_csv_drive_relu_avec_types_stables(self):
        """Un CSV relu depuis Drive (dates en texte, année en entier) retrouve les bons types."""
        raw = pl.DataFrame(
            {
                "date": ["2026-03-01"],
                "nom": ["x"],
                "categorie": ["Maison > Loyer"],
                "montant": [-850],
                "description": [None],
                "compte": ["PERSO"],
                "annee": [2026],
            }
        )
        df = preprocess_transactions_df(raw)
        assert df.schema["date"] == pl.Date
        assert df.schema["montant"] == pl.Float64
        assert df.schema["annee"] == pl.Utf8
        assert df.row(0, named=True)["description"] == ""

    def test_liste_vide_donne_schema_complet(self):
        df = preprocess_transactions([])
        assert df.is_empty()
        assert {"mois", "trimestre", "annee", "categorie-parent"} <= set(df.columns)


class TestFiltreCategories:
    def test_enfant_coche_sans_parent(self, sample_df):
        result = filter_by_categories(sample_df, ["Courses"])
        enfants = set(result["categorie-enfant"].to_list())
        assert enfants == {"Courses", ""}

    def test_lignes_sans_categorie_toujours_visibles(self, sample_df):
        result = filter_by_categories(sample_df, [])
        assert result.height == 1
        assert result.row(0, named=True)["montant"] == -10.0


class TestLissage:
    @pytest.mark.parametrize(
        ("lissage", "periode", "n_mois", "attendu"),
        [
            (False, "annee", 12, 1),
            (True, "mois", 1, 1),
            (True, "trimestre", 3, 3),
            (True, "trimestre", 2, 2),
            (True, "annee", 9, 9),
            (True, "annee", 0, 1),
        ],
    )
    def test_diviseur(self, lissage, periode, n_mois, attendu):
        assert smoothing_divisor(lissage, periode, n_mois) == attendu


class TestTotaux:
    def test_totaux_mensuels(self, sample_df):
        perso = sample_df.filter(pl.col("compte") == "PERSO")
        totals = compute_totals(perso, "mois", lissage=False).to_dicts()
        janvier = next(t for t in totals if t["mois"] == "2026-01")
        assert janvier == {"mois": "2026-01", "depenses": -120.0, "revenus": 2000.0, "epargne": 1880.0}

    def test_sans_categorie_compte_dans_les_depenses(self, sample_df):
        perso = sample_df.filter(pl.col("compte") == "PERSO")
        fevrier = next(t for t in compute_totals(perso, "mois", False).to_dicts() if t["mois"] == "2026-02")
        assert fevrier["depenses"] == pytest.approx(-150 - 30 + 50 - 10)

    def test_lissage_divise_par_les_mois_presents(self, sample_df):
        perso = sample_df.filter(pl.col("compte") == "PERSO")
        t1 = next(
            t for t in compute_totals(perso, "trimestre", True).to_dicts() if t["trimestre"] == "2026-T1"
        )
        brut = next(
            t for t in compute_totals(perso, "trimestre", False).to_dicts() if t["trimestre"] == "2026-T1"
        )
        assert t1["epargne"] == pytest.approx(brut["epargne"] / 2)

    def test_periode_sans_revenu_vaut_zero(self, sample_df):
        avril = next(t for t in compute_totals(sample_df, "mois", False).to_dicts() if t["mois"] == "2026-04")
        assert avril["revenus"] == 0.0

    def test_periodes_triees(self, sample_df):
        mois = compute_totals(sample_df, "mois", False)["mois"].to_list()
        assert mois == sorted(mois)


class TestCamembert:
    def test_vue_parent_avec_detail(self, sample_df):
        perso = sample_df.filter(pl.col("compte") == "PERSO")
        pie = compute_pie_data(perso, "mois", "2026-01", "parent", lissage=False)
        assert dict(zip(pie["label"], pie["montant"], strict=False)) == {"Quotidien": 100.0, "Loisirs": 20.0}
        detail = dict(zip(pie["label"], pie["hover_detail"], strict=False))
        assert detail["Quotidien"] == "Courses: -100€"

    def test_revenus_et_soldes_positifs_exclus(self, sample_df):
        perso = sample_df.filter(pl.col("compte") == "PERSO")
        pie = compute_pie_data(perso, "mois", "2026-02", "enfant", lissage=False)
        labels = pie["label"].to_list()
        assert "Salaire" not in labels
        assert "Pharmacie" not in labels  # -30 + 50 = remboursement net
        assert "hover_detail" not in pie.columns

    def test_periode_sans_depense(self, sample_df):
        pie = compute_pie_data(sample_df, "mois", "2030-01", "parent", lissage=False)
        assert pie.is_empty()

    def test_lissage_trimestre(self, sample_df):
        perso = sample_df.filter(pl.col("compte") == "PERSO")
        brut = compute_pie_data(perso, "trimestre", "2026-T1", "parent", lissage=False)
        lisse = compute_pie_data(perso, "trimestre", "2026-T1", "parent", lissage=True)
        assert lisse["montant"].sum() == pytest.approx(brut["montant"].sum() / 2)


class TestCouleurs:
    def test_categorie_inconnue_couleur_par_defaut(self):
        assert pie_colors_for_labels(["Inconnue", None], "parent") == [DEFAULT_PIE_COLOR] * 2

    def test_enfant_prend_la_couleur_du_parent(self, sample_df):
        mapping = enfant_parent_map(sample_df)
        couleurs = pie_colors_for_labels(["Courses", "Pharmacie"], "enfant", mapping)
        assert couleurs == pie_colors_for_labels(["Quotidien", "Santé"], "parent")


class TestStructure:
    def test_parents_connus_et_enfants_tries(self, sample_df):
        structure = category_structure(sample_df)
        assert structure["Quotidien"] == ["Boulangerie", "Courses"]
        assert structure["Dons"] == []
        assert "" not in structure

    def test_parent_inconnu_ajoute(self):
        df = preprocess_transactions(
            [
                {
                    "date": "2026-01-01",
                    "nom": "x",
                    "categorie": "Voyages > Avion",
                    "montant": -1.0,
                    "description": "",
                    "compte": "PERSO",
                }
            ]
        )
        assert category_structure(df)["Voyages"] == ["Avion"]
