"""Break-even-Rechnung und Kennzahlen für CourtSlot (Planannahmen, Stand 24.10.2026).

Aufruf: python docs/wirtschaftlichkeit/break_even.py
"""

import math

TENNISVEREINE_DE = 8731  # DTB Fact Sheet 2024

# Preisstaffel (Euro netto pro Monat) und angenommener Kundenanteil
PAKETE = {
    "S (bis 3 Plätze)": (19, 0.40),
    "M (4–6 Plätze)": (29, 0.45),
    "L (7–12 Plätze)": (49, 0.15),
}

FIXKOSTEN = {
    "Hosting und Betrieb (IONOS Cloud, inkl. Puffer)": 250,
    "E-Mail-Versand, Domain, Monitoring": 50,
    "Entwicklung und Support, 0,5 Stelle (Arbeitgeberkosten)": 3540,
    "Marketing und Vertrieb": 500,
}
VARIABLE_KOSTEN_JE_VEREIN = 3.0  # Zahlungsabwicklung, Support
NEUKUNDEN_PRO_MONAT = 10
CHURN_PRO_MONAT = 0.02


def monate_bis_break_even(break_even: int, churn: float, db: float, fix: float):
    """Monate bis zum monatlichen Break-even und kumulierter Verlust bis dahin."""
    kunden, monate, kumuliert = 0.0, 0, 0.0
    while kunden < break_even:
        monate += 1
        kunden = kunden * (1 - churn) + NEUKUNDEN_PRO_MONAT
        kumuliert += kunden * db - fix
        if monate > 600:
            return None, kumuliert
    return monate, kumuliert


def main() -> None:
    arpa = sum(preis * anteil for preis, anteil in PAKETE.values())
    fix = sum(FIXKOSTEN.values())
    db = arpa - VARIABLE_KOSTEN_JE_VEREIN
    break_even = math.ceil(fix / db)

    monate, verlust = monate_bis_break_even(break_even, CHURN_PRO_MONAT, db, fix)

    cac = FIXKOSTEN["Marketing und Vertrieb"] / NEUKUNDEN_PRO_MONAT
    ltv = db / CHURN_PRO_MONAT

    print(f"ARPA:                    {arpa:8.2f} €")
    print(f"Fixkosten:               {fix:8.2f} € pro Monat")
    print(f"Deckungsbeitrag/Verein:  {db:8.2f} €")
    print(f"Break-even:              {break_even:8d} Vereine "
          f"({break_even / TENNISVEREINE_DE:.1%} aller Tennisvereine)")
    print(f"MRR beim Break-even:     {break_even * arpa:8.0f} €")
    print(f"Monate bis Break-even:   {monate:8d}")
    print(f"Kumulierter Verlust bis dahin: {-verlust:8.0f} €")
    print(f"CAC:                     {cac:8.2f} €")
    print(f"Customer Lifetime Value: {ltv:8.2f} €  (LTV/CAC = {ltv / cac:.0f})")
    print("Hinweis: CAC enthält nur das Marketingbudget, keine Vertriebsarbeitszeit.")
    print("\nSensitivität der Kündigungsrate (Churn pro Monat):")
    for churn in (0.01, 0.02, 0.03, 0.05):
        m, v = monate_bis_break_even(break_even, churn, db, fix)
        ziel = f"{m} Monate" if m else "nicht erreicht"
        verlust_text = f"{-v:,.0f}".replace(",", ".")
        print(f"  {churn:.0%}: Break-even nach {ziel}; kumulierter Verlust {verlust_text} €")


if __name__ == "__main__":
    main()
