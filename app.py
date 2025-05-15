import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import polars as pl
import os
from dotenv import load_dotenv
from notion import get_transactions_from_notion
from drive import display_drive_message
from typing import Dict, List, Tuple, Optional

# Configuration des constantes
load_dotenv(override=True)
APP_PASSWORD = os.getenv("APP_PASSWORD")
if not APP_PASSWORD:
    raise ValueError("❌ La variable d'environnement APP_PASSWORD est requise")

ALPHA = 0.6

# Configuration des couleurs
CATEGORY_COLORS = {
    'Quotidien': f'rgba(255, 0, 0, {ALPHA})',        # Rouge
    'Loisirs': f'rgba(255, 165, 0, {ALPHA})',        # Orange
    'Sorties': f'rgba(128, 0, 128, {ALPHA})',        # Violet
    'Transports': f'rgba(0, 0, 250, {ALPHA})',       # Bleu
    'Maison': f'rgba(255, 255, 0, {ALPHA})',         # Jaune
    'Santé & Dons': f'rgba(255, 105, 180, {ALPHA})', # Rose
    'Revenus': f'rgba(0, 255, 0, {ALPHA})',          # Vert
    'Taxes': f'rgba(139, 69, 19, {ALPHA})',          # Marron
    'Exclus': f'rgba(128, 128, 128, {ALPHA})'        # Gris
}

MAP_PERIODE_NAMES = {"mois": "Mois", "trimestre": "Trimestre", "annee": "Année"}

# Configuration de la page
st.set_page_config(
    page_title="Budget",
    page_icon="💰",
    layout="wide"
)

# CSS personnalisé pour réduire les marges
st.markdown("""
    <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }
        .stDataFrame {
            padding: 0;
        }
        .stPlotlyChart {
            padding: 0;
        }
    </style>
""", unsafe_allow_html=True)

def check_password() -> bool:
    """Vérifie si le mot de passe est correct.
    
    Returns:
        bool: True si le mot de passe est correct
    """
    def password_entered():
        """Vérifie si le mot de passe est correct."""
        if st.session_state["password"] == APP_PASSWORD:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input(
            "Mot de passe", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        st.text_input(
            "Mot de passe", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Mot de passe incorrect")
        return False
    else:
        return True

def create_pie_chart(df_categories: pl.DataFrame, labels: List[str], map_categories: pl.DataFrame, groupe: str, periode_specifique: str) -> go.Figure:
    """Crée le graphique en camembert.
    
    Args:
        df_categories (pl.DataFrame): DataFrame des catégories
        labels (List[str]): Liste des labels
        map_categories (pl.DataFrame): Mapping des catégories
        groupe (str): Groupe de catégories
        periode_specifique (str): Période spécifique
        
    Returns:
        go.Figure: Figure Plotly
    """
    fig = go.Figure()
    fig.add_trace(go.Pie(
        labels=labels,
        values=df_categories['montant'].to_list(),
        marker=dict(
            colors=[CATEGORY_COLORS[map_categories.filter(pl.col(f"categorie-{groupe}") == cat).to_series().to_list()[0]] for cat in labels],
            line=dict(color='#B0B0B0', width=1)
        ),
        hovertemplate="%{label}: %{value:,.0f}€<br>%{percent:.1%}<extra></extra>"
    ))

    fig.update_traces(textposition='inside', textinfo='percent+label')
    fig.update_layout(
        title=dict(
            text=f'Dépenses par Catégorie sur {periode_specifique}',
            x=0.5,
            xanchor='center'
        ),
        uniformtext_minsize=10,
        uniformtext_mode='hide',
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.2,
            xanchor="center",
            x=0.5
        )
    )
    return fig

def create_bar_chart(df_totaux: pl.DataFrame, periode: str) -> go.Figure:
    """Crée le graphique en barres.
    
    Args:
        df_totaux (pl.DataFrame): DataFrame des totaux
        periode (str): Période
        
    Returns:
        go.Figure: Figure Plotly
    """
    fig = go.Figure()
    
    # Ajout des barres de dépenses et revenus
    fig.add_trace(go.Bar(
        x=df_totaux[periode].to_list(),
        y=df_totaux["depenses"].to_list(),
        name='Dépenses',
        marker_color=CATEGORY_COLORS['Quotidien'],
        hovertemplate="%{x}<br>Dépenses: %{y:,.0f}€<extra></extra>"
    ))
    fig.add_trace(go.Bar(
        x=df_totaux[periode].to_list(),
        y=df_totaux["revenus"].to_list(),
        name='Revenus',
        marker_color=CATEGORY_COLORS['Revenus'],
        hovertemplate="%{x}<br>Revenus: %{y:,.0f}€<extra></extra>"
    ))
    
    # Ajout de la courbe d'épargne
    fig.add_trace(go.Scatter(
        x=df_totaux[periode].to_list(),
        y=df_totaux["epargne"].to_list(),
        name='Épargne',
        mode='lines+markers',
        line=dict(color=CATEGORY_COLORS['Transports'], width=2),
        hovertemplate="%{x}<br>Épargne: %{y:,.0f}€<extra></extra>"
    ))

    fig.update_layout(
        title=dict(
            text=f'Épargne par {MAP_PERIODE_NAMES[periode]}',
            x=0.5,
            xanchor='center'
        ),
        barmode='group',
        xaxis_title=MAP_PERIODE_NAMES[periode],
        yaxis_title='Montant (€)',
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.2,
            xanchor="center",
            x=0.5
        ),
        dragmode=False
    )
    return fig

def create_sidebar_filters(df: pl.DataFrame) -> Tuple[str, str, str, List[str]]:
    """Crée les filtres dans la sidebar.
    
    Args:
        df (pl.DataFrame): DataFrame des transactions
        
    Returns:
        Tuple[str, str, str, List[str]]: Période, période spécifique, groupe, catégories sélectionnées
    """
    # Bouton de rechargement
    if st.sidebar.button("🔄 Recharger depuis Notion"):
        st.cache_data.clear()
        df = get_transactions_from_notion(force_reload=True)
        st.rerun()

    # Filtre de période
    st.sidebar.subheader("Temps")
    periode = st.sidebar.selectbox(
        "Type de période",
        ["mois", "trimestre", "annee"],
        format_func=lambda x: MAP_PERIODE_NAMES[x]
    )

    periodes = df.select(pl.col(periode)).unique().sort(periode, descending=True).to_series().to_list()
    periode_specifique = st.sidebar.selectbox("Période", periodes)

    # Filtre de catégories
    st.sidebar.subheader("Catégories")
    groupe = st.sidebar.selectbox(
        "Groupe",
        ["parent", "enfant"],
        format_func=lambda x: x.capitalize()
    )

    selected_categories = [
        cat for cat in CATEGORY_COLORS.keys()
        if st.sidebar.checkbox(
            cat,
            value=cat not in ['Exclus', 'Taxes'],
            key=f"cat_{cat}"
        )
    ]
    
    return periode, periode_specifique, groupe, selected_categories

def display_transactions_table(df: pl.DataFrame, periode: str, periode_specifique: str) -> None:
    """Affiche le tableau des transactions.
    
    Args:
        df (pl.DataFrame): DataFrame des transactions
        periode (str): Période
        periode_specifique (str): Période spécifique
    """
    st.subheader("Transactions")
    transactions_display = df.filter(pl.col(periode) == periode_specifique).select([
        "date", "nom", "categorie", "montant", "description"
    ]).to_pandas()

    st.dataframe(
        transactions_display.style.map(
            lambda x: f'color: {CATEGORY_COLORS["Quotidien"]}' if x < 0 else f'color: {CATEGORY_COLORS["Revenus"]}',
            subset=['montant']
        ),
        column_config={
            "date": st.column_config.DateColumn(
                "Date",
                format="YYYY-MM-DD"
            ),
            "nom": "Nom",
            "categorie": "Catégorie",
            "montant": st.column_config.NumberColumn(
                "Montant",
                format="%.2f €"
            ),
            "description": "Description"
        },
        hide_index=True
    )

def main() -> None:
    """Fonction principale de l'application."""
    st.title("Suivi Financier")

    if not check_password():
        st.stop()

    # Récupération des données
    df = get_transactions_from_notion()
    if df is None:
        st.error("❌ Impossible de charger les données")
        st.stop()
    
    # Affichage des messages Drive
    display_drive_message()
    
    # Création des filtres
    periode, periode_specifique, groupe, selected_categories = create_sidebar_filters(df)
    
    # Filtrage des données
    df = df.filter(
        pl.col("categorie-parent").is_in(selected_categories) | 
        pl.col("categorie-parent").is_null()
    )

    # Préparation des données pour les graphiques
    df_camembert = df.filter(pl.col("categorie-parent") != "Revenus")
    df_camembert = df_camembert.filter(pl.col(periode) == periode_specifique)

    df_categories = df_camembert.group_by(f"categorie-{groupe}").agg([
        pl.when(pl.col("montant").sum() < 0).then(pl.col("montant").sum().abs()).alias("montant")
    ])

    df_totaux = df.group_by(periode).agg([
        pl.col("montant").filter(pl.col("categorie-parent") != "Revenus").sum().alias("depenses"),
        pl.col("montant").filter(pl.col("categorie-parent") == "Revenus").sum().alias("revenus"),
        pl.col("montant").sum().alias("epargne")
    ]).sort(periode)

    # Création des graphiques
    map_categories = df.select(["categorie-parent", "categorie-enfant"]).unique()
    fig_categories = create_pie_chart(df_categories, df_categories[f"categorie-{groupe}"].to_list(), map_categories, groupe, periode_specifique)
    fig_totaux = create_bar_chart(df_totaux, periode)

    # Affichage des graphiques
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(fig_totaux, use_container_width=True, config={'displayModeBar': False})
    with col2:
        st.plotly_chart(fig_categories, use_container_width=True)

    # Affichage du tableau des transactions
    display_transactions_table(df, periode, periode_specifique)

if __name__ == "__main__":
    main() 