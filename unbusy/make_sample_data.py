"""
Make fake transactions (same format as fetch_transactions.py) to test the detector
without Plaid keys:

    python make_sample_data.py
    python detect_recurring.py sample_transactions.json

What the detector should find:
    Netflix   monthly, price went up last month
    Spotify   monthly, messy bank name "SQ *SPOTIFY 8X2Q"
    iCloud    monthly
    Duolingo  weekly
    Planet Fitness  monthly but stopped 3 months ago -> "stopped", not counted
    Amazon Prime    yearly, only 1 charge -> NOT detected (not enough history)
What it should ignore: Starbucks, groceries, Uber (random timing or amounts).
"""

import json
import random
from datetime import date, timedelta

random.seed(7)
START = date(2026, 4, 1)
END = date(2026, 10, 25)
txns = []


def add(day, name, amount, merchant_name=None):
    txns.append({
        "transaction_id": f"txn_{len(txns):04d}",
        "date": day.isoformat(),
        "name": name,
        "merchant_name": merchant_name,
        "amount": round(amount, 2),
        "account_id": "acc_checking",
        "category": None,
        "pending": False,
    })


def monthly(day_of_month, name, amount, start=START, end=END, merchant_name=None):
    d = start.replace(day=day_of_month)
    while d <= end:
        # Billing drifts a day or two sometimes, like real cards.
        add(d + timedelta(days=random.choice([0, 0, 0, 1, 2])), name, amount, merchant_name)
        d = (d.replace(day=1) + timedelta(days=32)).replace(day=day_of_month)


# Recurring
monthly(3, "NETFLIX.COM", 15.49, end=date(2026, 9, 30), merchant_name="Netflix")
add(date(2026, 10, 3), "NETFLIX.COM", 17.99, "Netflix")  # price increase
monthly(12, "SQ *SPOTIFY 8X2Q", 11.99)
monthly(20, "APPLE.COM/BILL ICLOUD 866-712-7753", 2.99)
monthly(1, "PLANET FITNESS #4412", 24.99, end=date(2026, 7, 15))  # cancelled in July
d = START + timedelta(days=2)
while d <= END:
    add(d, "DUOLINGO*PLUS", 3.49)
    d += timedelta(days=7)
add(date(2026, 6, 18), "AMAZON PRIME*2K4", 139.00, "Amazon Prime")

# Noise
d = START
while d <= END:
    if random.random() < 0.35:
        add(d, f"STARBUCKS STORE #{random.randint(1000, 9999)}", random.uniform(4.5, 9.5), "Starbucks")
    if random.random() < 0.12:
        add(d, "TRADER JOE S #552", random.uniform(35, 110), "Trader Joe's")
    if random.random() < 0.10:
        add(d, "UBER *TRIP", random.uniform(9, 32), "Uber")
    d += timedelta(days=1)

# Money coming in (negative amount) should be ignored.
d = START
while d <= END:
    add(d, "PAYROLL DIRECT DEP", -1250.00)
    d += timedelta(days=14)

txns.sort(key=lambda t: t["date"])
with open("sample_transactions.json", "w") as f:
    json.dump(txns, f, indent=2)
print(f"Wrote {len(txns)} fake transactions to sample_transactions.json")
