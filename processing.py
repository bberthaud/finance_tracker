"""Transformations pures (dates, filtres, lissage, agrégats, couleurs) — sans Streamlit ni APIs."""

from typing import Dict, List, Optional, TypedDict

import polars as pl

PERIODES = ("mois", "trimestre", "annee")
REVENUS = "Revenus"
DEFAULT_PIE_COLOR = "rgba(160, 160, 160, 0.85)"

CATEGORY_COLORS = {
    "Quotidien": "rgba(220, 20, 20, 0.85)",
    "Sorties": "rgba(128, 0, 128, 0.85)",
    "Loisirs": "rgba(230, 140, 0, 0.85)",
    "Transports": "rgba(0, 70, 200, 0.85)",
    "Maison": "rgba(139, 69, 19, 0.85)",
    "Santé": "rgba(220, 70, 140, 0.85)",
    "Dons": "rgba(200, 180, 0, 0.85)",
    "Revenus": "rgba(0, 160, 40, 0.85)",
    "Taxes": "rgba(90, 90, 90, 0.85)",
    "Exclus": "rgba(140, 140, 140, 0.85)",
}

CATEGORY_TEXT_COLORS = {
    "Quotidien": "#c40000",
    "Sorties": "#7a007a",
    "Loisirs": "#c46a00",
    "Transports": "#0038c8",
    "Maison": "#8b4513",
    "Santé": "#c42878",
    "Dons": "#8a7a00",
    "Revenus": "#008020",
    "Taxes": "#555555",
    "Exclus": "#777777",
}

DEFAULT_EXCLUDED_PARENTS = ("Exclus", "Taxes")


class Transaction(TypedDict):
    """Transaction telle que lue depuis Notion (avant prétraitement)."""

    date: str
    nom: str
    categorie: Optional[str]
    montant: Optional[float]
    description: str
    compte: Optional[str]


TRANSACTIONS_SCHEMA = {
    "date": pl.Date,
    "nom": pl.Utf8,
    "categorie": pl.Utf8,
    "montant": pl.Float64,
    "description": pl.Utf8,
    "compte": pl.Utf8,
    "mois": pl.Utf8,
    "trimestre": pl.Utf8,
    "annee": pl.Utf8,
    "categorie-parent": pl.Utf8,
    "categorie-enfant": pl.Utf8,
}


def empty_transactions() -> pl.DataFrame:
    return pl.DataFrame(schema=TRANSACTIONS_SCHEMA)


def preprocess_transactions_df(df: pl.DataFrame) -> pl.DataFrame:
    """Normalise dates, périodes (mois/trimestre/année) et catégories parent/enfant."""
    if df.is_empty():
        return empty_transactions()

    if df["date"].dtype == pl.Utf8:
        parsed = pl.col("date").str.slice(0, 10).str.strptime(pl.Date, "%Y-%m-%d", strict=False)
    else:
        parsed = pl.col("date").cast(pl.Date, strict=False)

    categorie = pl.col("categorie").cast(pl.Utf8).fill_null("")
    return (
        df.with_columns(
            [
                parsed.alias("date"),
                pl.col("montant").cast(pl.Float64, strict=False),
                pl.col("nom").cast(pl.Utf8).fill_null(""),
                pl.col("description").cast(pl.Utf8).fill_null(""),
            ]
        )
        .with_columns(
            [
                pl.col("date").dt.strftime("%Y-%m").alias("mois"),
                pl.concat_str(
                    [
                        pl.col("date").dt.year().cast(pl.Utf8),
                        pl.lit("-T"),
                        pl.col("date").dt.quarter().cast(pl.Utf8),
                    ]
                ).alias("trimestre"),
                pl.col("date").dt.year().cast(pl.Utf8).alias("annee"),
                categorie.str.split(" > ").list.first().alias("categorie-parent"),
                categorie.str.split(" > ").list.last().alias("categorie-enfant"),
            ]
        )
        .select(list(TRANSACTIONS_SCHEMA))
        .sort("date", descending=True)
    )


def preprocess_transactions(transactions: List[Transaction]) -> pl.DataFrame:
    if not transactions:
        return empty_transactions()
    return preprocess_transactions_df(pl.DataFrame(transactions))


def filter_by_categories(df: pl.DataFrame, selected_children: List[str]) -> pl.DataFrame:
    """Garde les lignes dont la catégorie enfant est cochée, et les lignes sans catégorie."""
    return df.filter(
        pl.col("categorie-enfant").is_in(selected_children)
        | pl.col("categorie-enfant").is_null()
        | (pl.col("categorie-enfant") == "")
    )


def smoothing_divisor(lissage: bool, periode: str, n_months: int) -> int:
    """Diviseur mensuel : nombre de mois présents, pas 12/3 fixes (année ou trimestre incomplets)."""
    if not lissage or periode == "mois":
        return 1
    return max(int(n_months or 0), 1)


def compute_totals(df: pl.DataFrame, periode: str, lissage: bool) -> pl.DataFrame:
    """Dépenses, revenus et épargne par période, éventuellement ramenés au mois."""
    divisor = pl.max_horizontal(pl.col("n_mois"), pl.lit(1)) if lissage and periode != "mois" else pl.lit(1)
    is_revenu = pl.col("categorie-parent") == REVENUS
    return (
        df.group_by(periode)
        .agg(
            [
                pl.col("mois").n_unique().alias("n_mois"),
                pl.col("montant").filter(~is_revenu).sum().alias("depenses"),
                pl.col("montant").filter(is_revenu).sum().alias("revenus"),
                pl.col("montant").sum().alias("epargne"),
            ]
        )
        .with_columns(divisor.alias("diviseur"))
        .with_columns(
            [
                (pl.col(c).fill_null(0.0) / pl.col("diviseur")).alias(c)
                for c in ("depenses", "revenus", "epargne")
            ]
        )
        .select([periode, "depenses", "revenus", "epargne"])
        .sort(periode)
    )


def compute_pie_data(
    df: pl.DataFrame, periode: str, periode_specifique: str, groupe: str, lissage: bool
) -> pl.DataFrame:
    """Dépenses (positives) par catégorie sur une période, avec détail des sous-catégories en vue parent.

    Colonnes : `label`, `montant`, et `hover_detail` (vue parent uniquement).
    Les catégories dont le solde est positif (remboursements) sont exclues.
    """
    cat_col = f"categorie-{groupe}"
    expenses = df.filter((pl.col(cat_col) != REVENUS) & (pl.col(periode) == periode_specifique))
    if expenses.is_empty():
        return pl.DataFrame(schema={"label": pl.Utf8, "montant": pl.Float64})

    divisor = smoothing_divisor(lissage, periode, expenses["mois"].n_unique())
    pie = (
        expenses.group_by(cat_col)
        .agg((pl.col("montant").sum() / divisor).alias("solde"))
        .filter(pl.col("solde") < 0)
        .select([pl.col(cat_col).alias("label"), (-pl.col("solde")).alias("montant")])
        .sort("montant", descending=True)
    )

    if groupe == "parent":
        details = (
            expenses.group_by(["categorie-parent", "categorie-enfant"])
            .agg((pl.col("montant").sum() / divisor).alias("montant"))
            .sort("montant")
            .with_columns(
                pl.format(
                    "{}: {}€",
                    "categorie-enfant",
                    pl.col("montant").map_elements(lambda x: f"{x:,.0f}", return_dtype=pl.Utf8),
                ).alias("ligne")
            )
            .group_by("categorie-parent", maintain_order=True)
            .agg(pl.col("ligne"))
            .select(
                [
                    pl.col("categorie-parent").alias("label"),
                    pl.col("ligne").list.join("<br>").alias("hover_detail"),
                ]
            )
        )
        pie = pie.join(details, on="label", how="left")

    return pie


def pie_colors_for_labels(
    labels: List[Optional[str]],
    groupe: str,
    enfant_to_parent: Optional[Dict[str, str]] = None,
) -> List[str]:
    mapping = enfant_to_parent or {}
    colors = []
    for label in labels:
        if label is None:
            colors.append(DEFAULT_PIE_COLOR)
            continue
        key = mapping.get(label, label) if groupe == "enfant" else label
        colors.append(CATEGORY_COLORS.get(key, DEFAULT_PIE_COLOR))
    return colors


def category_structure(df: pl.DataFrame) -> Dict[str, List[str]]:
    """Parents connus (même vides) puis parents découverts dans les données, avec leurs enfants triés."""
    structure: Dict[str, List[str]] = {parent: [] for parent in CATEGORY_COLORS}
    grouped = (
        df.filter(pl.col("categorie-parent").is_not_null() & (pl.col("categorie-parent") != ""))
        .group_by("categorie-parent")
        .agg(pl.col("categorie-enfant").drop_nulls().unique().sort())
        .sort("categorie-parent")
    )
    for row in grouped.iter_rows(named=True):
        structure[row["categorie-parent"]] = [c for c in row["categorie-enfant"] if c]
    return structure


def enfant_parent_map(df: pl.DataFrame) -> Dict[str, str]:
    pairs = df.select(["categorie-parent", "categorie-enfant"]).unique().drop_nulls()
    return {
        row["categorie-enfant"]: row["categorie-parent"]
        for row in pairs.iter_rows(named=True)
        if row["categorie-enfant"]
    }
