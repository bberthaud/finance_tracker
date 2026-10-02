"""Génère un jeu de transactions fictives et reproductible pour le mode démo.

Usage : python scripts/generate_demo_data.py
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "demo" / "transactions_demo.csv"
START = date(2025, 1, 1)
END = date(2026, 9, 30)

# (catégorie, libellés possibles, montant min, montant max, occurrences par mois)
DEPENSES = [
    ("Quotidien > Courses", ["Carrefour", "Monoprix", "Biocoop"], 15, 120, 8),
    ("Quotidien > Boulangerie", ["Boulangerie Paul", "Maison Kayser"], 2, 12, 6),
    ("Sorties > Restaurants", ["Pizzeria Napoli", "Sushi Shop", "Le Bistrot"], 15, 70, 3),
    ("Sorties > Bars", ["Le Comptoir", "Brewdog"], 8, 40, 2),
    ("Loisirs > Streaming", ["Netflix", "Spotify"], 9, 18, 2),
    ("Loisirs > Sport", ["Basic Fit", "Decathlon"], 20, 60, 1),
    ("Transports > Carburant", ["Total Energies", "Esso"], 40, 80, 2),
    ("Transports > Train", ["SNCF Connect"], 25, 120, 1),
    ("Maison > Loyer", ["Agence Immo"], 850, 850, 1),
    ("Maison > Électricité", ["EDF"], 45, 90, 1),
    ("Santé > Pharmacie", ["Pharmacie du Centre"], 5, 40, 1),
    ("Dons > Associations", ["Restos du Coeur", "Croix Rouge"], 10, 30, 1),
    ("Taxes > Impôts", ["DGFIP"], 150, 300, 1),
    ("Exclus > Virement interne", ["Virement épargne"], 200, 400, 1),
]


def month_starts(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)


def random_day(rng: random.Random, month: date) -> date:
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return month + timedelta(days=rng.randrange((next_month - month).days))


def generate(seed: int = 42):
    rng = random.Random(seed)
    rows = []
    for month in month_starts(START, END):
        for compte, salaire in (("PERSO", 2600), ("JOINT", 1500)):
            rows.append(
                (
                    month.replace(day=1),
                    "Salaire" if compte == "PERSO" else "Virement commun",
                    "Revenus > Salaire",
                    salaire,
                    "VIR SEPA",
                    compte,
                )
            )
            factor = 1.0 if compte == "PERSO" else 0.6
            for categorie, labels, low, high, per_month in DEPENSES:
                for _ in range(max(1, round(per_month * factor))):
                    amount = round(rng.uniform(low, high), 2)
                    label = rng.choice(labels)
                    rows.append(
                        (random_day(rng, month), label, categorie, -amount, f"CB {label.upper()}", compte)
                    )
            if rng.random() < 0.5:
                rows.append(
                    (
                        random_day(rng, month),
                        "Remboursement Ameli",
                        "Santé > Pharmacie",
                        round(rng.uniform(5, 30), 2),
                        "VIR CPAM",
                        compte,
                    )
                )
            rows.append(
                (
                    random_day(rng, month),
                    "Paiement non catégorisé",
                    "",
                    -round(rng.uniform(5, 50), 2),
                    "CB DIVERS",
                    compte,
                )
            )

    rows = [r for r in rows if r[0] <= END]
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "nom", "categorie", "montant", "description", "compte"])
        for d, nom, categorie, montant, description, compte in generate():
            writer.writerow([d.isoformat(), nom, categorie, montant, description, compte])
    print(f"Écrit : {OUTPUT}")


if __name__ == "__main__":
    main()
