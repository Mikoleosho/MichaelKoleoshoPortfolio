"""
Step 2: Find recurring charges (subscriptions) in transactions.json.

    python detect_recurring.py                       # reads transactions.json
    python detect_recurring.py sample_transactions.json

Four checks per merchant:
    1. Clean up names    - "SQ *SPOTIFY 8X2Q" -> "spotify"
    2. Same amount       - keep charges within 20% of the merchant's usual amount
    3. Regular timing    - at least 3 charges with consistent gaps (weekly ... yearly)
    4. Still active      - last charge within ~1.5 billing cycles, else "stopped"

Prints a table plus the headline number, and writes recurring.json for the app.
"""

import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta

AMOUNT_TOLERANCE = 0.20      # check 2: within 20% of the usual amount
MIN_CHARGES = 3              # check 3: need at least this many charges
GAP_FIT_SHARE = 0.66         # check 3: share of gaps that must fit the cadence
STOPPED_AFTER_CYCLES = 1.5   # check 4: stopped if no charge in 1.5 cycles
PRICE_INCREASE = 0.10        # flag if latest charge is >10% above the usual

# name, typical days between charges, allowed slack in days
CADENCES = [
    ("weekly", 7, 2),
    ("biweekly", 14, 3),
    ("monthly", 30.44, 5),
    ("quarterly", 91.3, 10),
    ("yearly", 365.25, 20),
]

# Payment processors and card-network junk that banks put in front of names.
PREFIXES = re.compile(
    r"^(sq \*|sq\*|tst\*|tst \*|pp\*|paypal \*|paypal\*|sp \*|sp\*|py \*|"
    r"pos |debit card purchase |recurring payment |purchase |ach )+"
)
NOISE_WORDS = {"inc", "llc", "ltd", "co", "com", "www", "usa", "us", "the",
               "subscription", "membership", "bill", "payment", "autopay"}


def clean_name(txn):
    """Check 1: turn messy bank text into a stable merchant key.

    Uses Plaid's merchant_name when it has one. Names a rule can't fix are a
    good place to call the Claude API later.
    """
    raw = (txn.get("merchant_name") or txn["name"]).lower().strip()
    raw = PREFIXES.sub("", raw)
    raw = raw.replace(".com", " ").replace(".net", " ")
    words = re.sub(r"[^a-z0-9 ]", " ", raw).split()
    # Drop ID numbers, store numbers and filler words ("8x2q", "#4412", "inc").
    words = [w for w in words if not any(c.isdigit() for c in w) and w not in NOISE_WORDS]
    return " ".join(words) or raw


def match_cadence(gaps):
    """Check 3: return (name, days) of the cadence most gaps fit, or None."""
    typical = statistics.median(gaps)
    for name, days, slack in CADENCES:
        if abs(typical - days) <= slack:
            fits = sum(1 for g in gaps if abs(g - days) <= slack)
            if fits / len(gaps) >= GAP_FIT_SHARE:
                return name, days
    return None


def analyze_merchant(merchant, txns, as_of):
    usual = statistics.median(t["amount"] for t in txns)

    # Check 2: only charges close to the usual amount. Random Starbucks runs fail here
    # (or in check 3), so they don't look like subscriptions.
    charges = [t for t in txns if abs(t["amount"] - usual) <= AMOUNT_TOLERANCE * usual]
    # Count at most one charge per day (bank sometimes splits or duplicates).
    by_day = {}
    for t in charges:
        by_day.setdefault(t["date"], t)
    charges = [by_day[d] for d in sorted(by_day)]
    if len(charges) < MIN_CHARGES:
        return None

    dates = [date.fromisoformat(t["date"]) for t in charges]
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    cadence = match_cadence(gaps)
    if not cadence:
        return None
    cadence_name, cadence_days = cadence

    # Check 4: still active?
    last = dates[-1]
    days_since = (as_of - last).days
    active = days_since <= STOPPED_AFTER_CYCLES * cadence_days

    amounts = [t["amount"] for t in charges]
    usual = statistics.median(amounts)
    latest = amounts[-1]
    earlier = statistics.median(amounts[:-1])
    return {
        "merchant": merchant,
        "display_name": charges[-1].get("merchant_name") or merchant.title(),
        "cadence": cadence_name,
        "usual_amount": round(usual, 2),
        "latest_amount": round(latest, 2),
        "monthly_cost": round(latest * 30.44 / cadence_days, 2),
        "charge_count": len(charges),
        "first_charge": dates[0].isoformat(),
        "last_charge": last.isoformat(),
        "next_expected": (last + timedelta(days=round(cadence_days))).isoformat() if active else None,
        "status": "active" if active else "stopped",
        "price_increase": latest > earlier * (1 + PRICE_INCREASE),
    }


def detect(transactions, as_of=None):
    # Only money leaving the account (Plaid: positive amount = outflow).
    outflows = [t for t in transactions if t["amount"] > 0 and not t.get("pending")]
    if as_of is None:
        as_of = max(date.fromisoformat(t["date"]) for t in outflows)

    groups = defaultdict(list)
    for t in outflows:
        groups[clean_name(t)].append(t)

    results = [r for m, txns in groups.items() if (r := analyze_merchant(m, txns, as_of))]
    results.sort(key=lambda r: (r["status"] != "active", -r["monthly_cost"]))
    return results


def print_report(results):
    print(f"{'Merchant':<22}{'Cadence':<11}{'Amount':>9}{'Per month':>11}  {'Last charge':<12}Status")
    print("-" * 78)
    for r in results:
        flag = "  (price went up)" if r["price_increase"] else ""
        print(f"{r['display_name'][:21]:<22}{r['cadence']:<11}{r['latest_amount']:>9.2f}"
              f"{r['monthly_cost']:>11.2f}  {r['last_charge']:<12}{r['status']}{flag}")
    active = [r for r in results if r["status"] == "active"]
    total = sum(r["monthly_cost"] for r in active)
    print("-" * 78)
    print(f"You're paying about ${total:,.2f}/month (${total * 12:,.0f}/year) "
          f"across {len(active)} recurring charges.")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "transactions.json"
    with open(path) as f:
        transactions = json.load(f)
    results = detect(transactions)
    print_report(results)
    with open("recurring.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Saved results to recurring.json")


if __name__ == "__main__":
    main()
