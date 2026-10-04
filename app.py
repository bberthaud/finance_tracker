import hmac
import os
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

import plotly.graph_objects as go
import polars as pl
import streamlit as st
from dotenv import load_dotenv

from drive import DriveOutcome, build_drive_service, load_from_drive, save_to_drive
from processing import (
    CATEGORY_COLORS,
    CATEGORY_TEXT_COLORS,
    DEFAULT_EXCLUDED_PARENTS,
    PERIODES,
    category_structure,
    compute_pie_data,
    compute_totals,
    enfant_parent_map,
    filter_by_categories,
    pie_colors_for_labels,
    preprocess_transactions_df,
)

load_dotenv(override=False)

DEFAULT_DEMO_CSV = Path(__file__).parent / "demo" / "transactions_demo.csv"
MAP_PERIODE_NAMES = {"mois": "Mois", "trimestre": "Trimestre", "annee": "Année"}
PLOTLY_CONFIG = {"displayModeBar": False}
CHART_HEIGHT = 450
COMPTES = ["PERSO", "JOINT"]
HIDE_AMOUNTS_KEY = "masquer_montants"
HIDDEN_AMOUNT = "••• €"
NO_EXPENSE_MESSAGE = "Aucune dépense à afficher pour cette période."


class DataLoadError(Exception):
    """Levée (plutôt que retourner None) pour que Streamlit ne mette pas l'échec en cache."""


class Filters(NamedTuple):
    compte: str
    periode: str
    periode_specifique: Optional[str]
    lissage: bool
    groupe: str
    categories: List[str]


def is_demo_mode() -> bool:
    return os.getenv("DATA_SOURCE", "").lower() == "demo"


def amounts_hidden() -> bool:
    return bool(st.session_state.get(HIDE_AMOUNTS_KEY))


def check_password() -> bool:
    app_password = os.getenv("APP_PASSWORD")
    if not app_password:
        st.error("❌ La variable d'environnement APP_PASSWORD est requise")
        return False

    def password_entered():
        typed = st.session_state.get("password", "")
        st.session_state["password_correct"] = hmac.compare_digest(typed.encode(), app_password.encode())
        if st.session_state["password_correct"]:
            del st.session_state["password"]

    if st.session_state.get("password_correct"):
        return True

    st.text_input("Mot de passe", type="password", on_change=password_entered, key="password")
    if st.session_state.get("password_correct") is False:
        st.error("😕 Mot de passe incorrect")
    return False


@st.cache_resource(show_spinner=False)
def get_drive_service():
    try:
        info = dict(st.secrets["gcp_service_account"])
    except Exception as exc:
        raise DataLoadError(f"Identifiants Google Drive absents des secrets Streamlit ({exc})") from exc
    try:
        return build_drive_service(info)
    except Exception as exc:
        raise DataLoadError(f"Authentification Google Drive impossible ({exc})") from exc


def store_drive_message(outcome: DriveOutcome) -> None:
    if outcome.message:
        st.session_state.drive_message = {
            "type": outcome.status,
            "message": outcome.message,
            "icon": outcome.icon,
        }


def display_drive_message() -> None:
    message = st.session_state.get("drive_message")
    if not message:
        return
    display = {"success": st.success, "error": st.error, "warning": st.warning}.get(message["type"])
    if display:
        display(message["message"], icon=message["icon"])


@st.cache_data(ttl=3600, show_spinner="Chargement des transactions…")
def get_transactions() -> pl.DataFrame:
    if is_demo_mode():
        path = Path(os.getenv("DEMO_DATA_PATH") or DEFAULT_DEMO_CSV)
        if not path.is_file():
            raise DataLoadError(f"Fichier de démo introuvable : {path}")
        return preprocess_transactions_df(pl.read_csv(path, infer_schema_length=None))
    outcome = load_from_drive(get_drive_service())
    if outcome.df is None:
        raise DataLoadError(outcome.message)
    return preprocess_transactions_df(outcome.df)


def reload_from_notion() -> None:
    from notion import fetch_transactions_from_notion

    df = fetch_transactions_from_notion()
    store_drive_message(save_to_drive(get_drive_service(), df))


def pie_title(periode_specifique: str, lissage: bool) -> str:
    return f"Dépenses par Catégorie sur {periode_specifique}" + (" (/mois)" if lissage else "")


def create_pie_chart(
    pie: pl.DataFrame,
    colors: List[str],
    periode_specifique: str,
    lissage: bool,
    hide_amounts: bool = False,
) -> go.Figure:
    hover_template = "<b>%{label}</b> (%{percent:.1%})"
    customdata = None
    if hide_amounts:
        total = HIDDEN_AMOUNT
    else:
        total = f"-{pie['montant'].sum():,.0f}€"
        hover_template += "<br>Total: -%{value:,.0f}€"
        if "hover_detail" in pie.columns:
            hover_template += "<br><br>%{customdata}"
            customdata = pie["hover_detail"].to_list()
    hover_template += "<extra></extra>"

    fig = go.Figure(
        go.Pie(
            labels=pie["label"].to_list(),
            values=pie["montant"].to_list(),
            marker=dict(colors=colors, line=dict(color="#B0B0B0", width=1)),
            hovertemplate=hover_template,
            customdata=customdata,
            hole=0.4,
        )
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(
        title=dict(text=pie_title(periode_specifique, lissage), x=0.5, xanchor="center"),
        height=CHART_HEIGHT,
        uniformtext_minsize=10,
        uniformtext_mode="hide",
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
        annotations=[dict(text=total, x=0.5, y=0.5, showarrow=False)],
    )
    return fig


def create_empty_pie_placeholder(periode_specifique: str, lissage: bool) -> go.Figure:
    """Figure vide de la taille du camembert, avec le message centré à sa place."""
    fig = go.Figure()
    fig.update_layout(
        title=dict(text=pie_title(periode_specifique, lissage), x=0.5, xanchor="center"),
        height=CHART_HEIGHT,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor="rgba(0,0,0,0)",
        annotations=[
            dict(
                text=NO_EXPENSE_MESSAGE,
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=16),
            )
        ],
        dragmode=False,
    )
    return fig


def create_bar_chart(
    totals: pl.DataFrame, periode: str, lissage: bool, hide_amounts: bool = False
) -> go.Figure:
    title = f"Épargne par {MAP_PERIODE_NAMES[periode]}" + (" (/mois)" if lissage else "")
    x = totals[periode].to_list()

    def hover(name: str) -> str:
        amount = "" if hide_amounts else ": %{y:,.0f}€"
        return f"%{{x}}<br>{name}{amount}<extra></extra>"

    fig = go.Figure(
        [
            go.Bar(
                x=x,
                y=totals["depenses"].to_list(),
                name="Dépenses",
                marker_color=CATEGORY_COLORS["Quotidien"],
                hovertemplate=hover("Dépenses"),
            ),
            go.Bar(
                x=x,
                y=totals["revenus"].to_list(),
                name="Revenus",
                marker_color=CATEGORY_COLORS["Revenus"],
                hovertemplate=hover("Revenus"),
            ),
            go.Scatter(
                x=x,
                y=totals["epargne"].to_list(),
                name="Épargne",
                mode="lines+markers",
                line=dict(color=CATEGORY_COLORS["Transports"], width=2),
                hovertemplate=hover("Épargne"),
            ),
        ]
    )
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor="center"),
        height=CHART_HEIGHT,
        barmode="group",
        xaxis_title=MAP_PERIODE_NAMES[periode],
        yaxis=dict(title="Montant (€)", showticklabels=not hide_amounts),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
        dragmode=False,
    )
    return fig


def create_sidebar_filters(df: pl.DataFrame) -> Filters:
    if not is_demo_mode() and st.sidebar.button("🔄 Recharger depuis Notion"):
        st.cache_data.clear()
        try:
            reload_from_notion()
        except Exception as exc:
            st.session_state.drive_message = {
                "type": "error",
                "message": f"Rechargement depuis Notion impossible : {exc}",
                "icon": "❌",
            }
        st.rerun()

    compte = st.sidebar.selectbox("Compte", COMPTES, index=0)

    st.sidebar.subheader("Temps")
    periode = st.sidebar.selectbox(
        "Type de période", list(PERIODES), format_func=lambda x: MAP_PERIODE_NAMES[x]
    )
    periodes = df[periode].unique().sort(descending=True).to_list()
    periode_specifique = st.sidebar.selectbox("Période", periodes) if periodes else None
    lissage = st.sidebar.checkbox("Lissage Mensuel", value=False)

    st.sidebar.subheader("Catégories")
    groupe = st.sidebar.selectbox("Groupe", ["parent", "enfant"], format_func=str.capitalize)

    structure = category_structure(df)
    init_category_state(structure)
    select_all, unselect_all = st.sidebar.columns(2)
    select_all.button(
        "Tout sélectionner", key="select_all", on_click=set_all_categories, args=(structure, True)
    )
    unselect_all.button(
        "Tout désélectionner", key="unselect_all", on_click=set_all_categories, args=(structure, False)
    )

    selected: List[str] = []
    for parent, children in structure.items():
        with st.sidebar.expander(parent):
            parent_checked = st.checkbox(f"**{parent}**", key=parent_key(parent))
            if not children and parent_checked:
                selected.append(parent)
            for child in children:
                if st.checkbox(f"• {child}", key=child_key(parent, child)):
                    selected.append(child)

    return Filters(compte, periode, periode_specifique, lissage, groupe, selected)


def parent_key(parent: str) -> str:
    return f"parent_{parent}"


def child_key(parent: str, child: str) -> str:
    return f"child_{parent}_{child}"


def init_category_state(structure: Dict[str, List[str]]) -> None:
    """Valeurs initiales posées dans session_state (et non via `value=`) : sinon Streamlit avertit
    quand `set_all_categories` modifie les cases. Un enfant démarre à la valeur de son parent."""
    for parent, children in structure.items():
        st.session_state.setdefault(parent_key(parent), parent not in DEFAULT_EXCLUDED_PARENTS)
        for child in children:
            st.session_state.setdefault(child_key(parent, child), st.session_state[parent_key(parent)])


def set_all_categories(structure: Dict[str, List[str]], checked: bool) -> None:
    for parent, children in structure.items():
        st.session_state[parent_key(parent)] = checked
        for child in children:
            st.session_state[child_key(parent, child)] = checked


def display_transactions_table(
    df: pl.DataFrame, periode: str, periode_specifique: str, hide_amounts: bool = False
) -> None:
    st.subheader("Transactions")
    table = (
        df.filter(pl.col(periode) == periode_specifique)
        .select(["date", "nom", "categorie", "montant", "description", "compte"])
        .to_pandas()
    )

    def montant_color(value):
        key = "Quotidien" if value < 0 else "Revenus"
        return f"color: {CATEGORY_TEXT_COLORS[key]}"

    def categorie_color(value):
        color = CATEGORY_TEXT_COLORS.get(str(value or "").split(" > ")[0])
        return f"color: {color}" if color else ""

    if hide_amounts:
        table["montant"] = HIDDEN_AMOUNT
        styled = table.style
        montant_column = st.column_config.TextColumn("Montant")
    else:
        styled = table.style.map(montant_color, subset=["montant"])
        montant_column = st.column_config.NumberColumn("Montant", format="%.2f €")

    st.dataframe(
        styled.map(categorie_color, subset=["categorie"]),
        column_config={
            "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
            "nom": "Nom",
            "categorie": "Catégorie",
            "montant": montant_column,
            "description": "Description",
            "compte": "Compte",
        },
        hide_index=True,
    )


def main() -> None:
    st.set_page_config(page_title="Budget", page_icon="💰", layout="wide")
    st.markdown(
        """
        <style>
            .block-container { padding: 2rem; }
            .stDataFrame, .stPlotlyChart { padding: 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Suivi Financier")
    if is_demo_mode():
        st.caption("Mode démo : données fictives")
    st.sidebar.toggle("Masquer les montants", key=HIDE_AMOUNTS_KEY)
    hide_amounts = amounts_hidden()

    if not check_password():
        st.stop()

    try:
        df = get_transactions()
    except DataLoadError as exc:
        st.error(f"❌ Impossible de charger les données : {exc}")
        st.stop()

    display_drive_message()
    f = create_sidebar_filters(df)

    df = filter_by_categories(df.filter(pl.col("compte") == f.compte), f.categories)
    if df.is_empty() or not f.periode_specifique:
        st.info("Aucune transaction pour ces filtres.")
        return

    pie = compute_pie_data(df, f.periode, f.periode_specifique, f.groupe, f.lissage)

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            create_bar_chart(compute_totals(df, f.periode, f.lissage), f.periode, f.lissage, hide_amounts),
            use_container_width=True,
            config=PLOTLY_CONFIG,
        )
    with col2:
        if pie.is_empty():
            fig = create_empty_pie_placeholder(f.periode_specifique, f.lissage)
        else:
            colors = pie_colors_for_labels(pie["label"].to_list(), f.groupe, enfant_parent_map(df))
            fig = create_pie_chart(pie, colors, f.periode_specifique, f.lissage, hide_amounts)
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

    display_transactions_table(df, f.periode, f.periode_specifique, hide_amounts)


if __name__ == "__main__":
    main()
