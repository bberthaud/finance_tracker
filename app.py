import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import polars as pl
from notion_client import Client
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# Configuration des constantes
load_dotenv(override=True)
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
APP_PASSWORD = os.getenv("APP_PASSWORD")
ALPHA = 0.7

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

# Initialisation du client Notion
notion = Client(auth=NOTION_TOKEN)

# Configuration de la page
st.set_page_config(
    page_title="Suivi Financier",
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

# Fonction pour vérifier le mot de passe
def check_password():
    """Retourne `True` si le mot de passe est correct."""
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

def load_transactions_from_csv():
    """Charge les transactions depuis le fichier CSV"""
    try:
        df = pl.read_csv("exports/transactions.csv", schema_overrides={"annee": pl.Utf8})
        return df
    except Exception as e:
        st.sidebar.error(f"❌ Erreur lors du chargement du CSV: {e}")
        return None

def preprocess_transactions(transactions):
    """Prétraite les transactions pour l'affichage"""
    df = pl.DataFrame(transactions)
    
    # Conversion de la date et création des colonnes temporelles
    df = df.with_columns([
        pl.col("date").str.strptime(pl.Date, "%Y-%m-%d").alias("date")
    ])

    df = df.with_columns([
        pl.col("date").dt.strftime("%Y-%m").alias("mois"),
        pl.concat_str([
            pl.col("date").dt.year().cast(pl.Utf8),
            pl.lit("-T"),
            pl.col("date").dt.quarter().cast(pl.Utf8)
        ]).alias("trimestre"),
        pl.col("date").dt.year().cast(pl.Utf8).alias("annee"),
        pl.col("categorie").str.split(" > ").list.first().alias("categorie-parent"),
        pl.col("categorie").str.split(" > ").list.last().alias("categorie-enfant")
    ])
    
    return df.sort("date", descending=True)

@st.cache_data(ttl=3600, show_spinner="Chargement des transactions depuis Notion...")
def get_transactions(force_reload=False):
    """Récupère les transactions depuis Notion ou le CSV"""
    csv_path = "exports/transactions.csv"
    
    # Vérification du CSV si pas de rechargement forcé
    if not force_reload and os.path.exists(csv_path):
        file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(csv_path))
        if file_age < timedelta(hours=12):
            return load_transactions_from_csv()

    # Récupération depuis Notion
    transactions = []
    has_more = True
    start_cursor = None

    while has_more:
        response = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            start_cursor=start_cursor
        )

        for page in response["results"]:
            props = page["properties"]
            transactions.append({
                "date": props["Date"]["date"]["start"],
                "nom": props["Nom"]["title"][0]["text"]["content"],
                "categorie": props["Catégorie"]["select"]["name"],
                "montant": props["Montant"]["number"],
                "description": props["Description"]["rich_text"][0]["text"]["content"]
            })

        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    df = preprocess_transactions(transactions)
    df.write_csv(csv_path)
    return df

def create_pie_chart(df_categories, labels, map_categories, groupe, periode_specifique):
    """Crée le graphique en camembert"""
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
        title=f'Dépenses par Catégorie sur {periode_specifique}',
        uniformtext_minsize=10,
        uniformtext_mode='hide'
    )
    return fig

def create_bar_chart(df_totaux, periode):
    """Crée le graphique en barres"""
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
        title=f'Epargne par {periode.capitalize()}',
        barmode='group',
        xaxis_title=periode.capitalize(),
        yaxis_title='Montant (€)'
    )
    return fig

def create_sidebar_filters(df):
    """Crée les filtres dans la sidebar"""
    # Bouton de rechargement
    if st.sidebar.button("🔄 Recharger depuis Notion"):
        st.cache_data.clear()
        df = get_transactions(force_reload=True)
        st.rerun()

    # st.sidebar.header("Filtres")
    
    # Filtre de période
    st.sidebar.subheader("Temps")
    periode = st.sidebar.selectbox(
        "Type de période",
        ["mois", "trimestre", "annee"],
        format_func=lambda x: x.capitalize()
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

def display_transactions_table(df, periode, periode_specifique):
    """Affiche le tableau des transactions"""
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

def main():
    st.title("Suivi Financier")

    if not check_password():
        st.stop()

    # Récupération des données
    df = get_transactions()
    
    # Création des filtres
    periode, periode_specifique, groupe, selected_categories = create_sidebar_filters(df)
    
    # Filtrage des données
    df = df.filter(pl.col("categorie-parent").is_in(selected_categories))

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
        st.plotly_chart(fig_totaux, use_container_width=True)
    with col2:
        st.plotly_chart(fig_categories, use_container_width=True)

    # Affichage du tableau des transactions
    display_transactions_table(df, periode, periode_specifique)

if __name__ == "__main__":
    main() 