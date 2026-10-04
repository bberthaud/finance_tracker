"""Tests de propriétés (Hypothesis) : des invariants vérifiés sur des centaines d'entrées générées."""

from datetime import date

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from bank import is_existing_transaction, storage_transaction_id
from processing import (
    DAYS_PER_MONTH,
    compute_totals,
    period_label,
    preprocess_transactions,
    smoothing_divisor,
)

CATEGORIES = ["Quotidien > Courses", "Loisirs > Sport", "Revenus > Salaire", None]

transactions = st.lists(
    st.fixed_dictionaries(
        {
            "date": st.dates(min_value=date(2024, 1, 1), max_value=date(2026, 12, 31)).map(str),
            "nom": st.just("op"),
            "categorie": st.sampled_from(CATEGORIES),
            "montant": st.floats(min_value=-5000, max_value=5000, allow_nan=False).map(lambda x: round(x, 2)),
            "description": st.just(""),
            "compte": st.sampled_from(["PERSO", "JOINT"]),
        }
    ),
    min_size=1,
    max_size=60,
)

ids = st.text(alphabet="abcdef0123456789", min_size=1, max_size=12)


@given(
    st.booleans(), st.sampled_from(["mois", "trimestre", "annee"]), st.integers(min_value=-5, max_value=24)
)
def test_diviseur_toujours_positif(lissage, periode, n_mois):
    assert smoothing_divisor(lissage, periode, n_mois) >= 1


@given(
    st.sampled_from(["mois", "trimestre", "annee"]),
    st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
    st.integers(min_value=0, max_value=12),
)
def test_diviseur_periode_en_cours_borne(periode, today, n_mois):
    """Période en cours : au moins 1 mois, au plus la durée de la période (3 ou 12 mois)."""
    divisor = smoothing_divisor(True, periode, n_mois, period_label(periode, today), today)
    assert (
        1 <= divisor <= {"mois": 1, "trimestre": 92 / DAYS_PER_MONTH, "annee": 366 / DAYS_PER_MONTH}[periode]
    )


@given(st.sampled_from(["PERSO", "JOINT"]), ids)
def test_prefixe_idempotent_et_reconnu(compte, raw):
    stored = storage_transaction_id(compte, raw)
    assert storage_transaction_id(compte, stored) == stored
    assert is_existing_transaction(stored, {raw})


@settings(max_examples=50, deadline=None)
@given(transactions, st.sampled_from(["mois", "trimestre", "annee"]))
def test_epargne_egale_depenses_plus_revenus(rows, periode):
    totals = compute_totals(preprocess_transactions(rows), periode, lissage=False)
    for row in totals.iter_rows(named=True):
        assert abs(row["epargne"] - (row["depenses"] + row["revenus"])) < 1e-6


@settings(max_examples=50, deadline=None)
@given(transactions)
def test_aucune_transaction_perdue_entre_les_periodes(rows):
    df = preprocess_transactions(rows)
    for periode in ("mois", "trimestre", "annee"):
        totals = compute_totals(df, periode, lissage=False)
        assert abs(totals["epargne"].sum() - df["montant"].sum()) < 1e-6
    assert df.filter(pl.col("mois").is_null()).is_empty()
