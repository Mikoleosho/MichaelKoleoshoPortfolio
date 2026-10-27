"""
Step 1: Pull transactions from Plaid (Sandbox) and save them to transactions.json.

Setup:
    1. Sign up at https://dashboard.plaid.com and copy your Sandbox keys.
    2. pip install plaid-python
    3. export PLAID_CLIENT_ID=...  and  export PLAID_SECRET=...   (Sandbox secret)
    4. python fetch_transactions.py

In a real app the user logs in through Plaid Link (the pop-up) and your server
gets a public_token from it. Sandbox lets us skip the pop-up and create that
token directly with a fake bank and a fake user.
"""

import json
import os
import sys
import time

import plaid
from plaid.api import plaid_api
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.sandbox_public_token_create_request_options import SandboxPublicTokenCreateRequestOptions
from plaid.model.transactions_sync_request import TransactionsSyncRequest

SANDBOX_BANK = "ins_109508"  # "First Platypus Bank", a fake Sandbox bank
TEST_USER = "user_transactions_dynamic"  # comes with ~6 months of realistic transactions
OUTPUT_FILE = "transactions.json"


def make_client():
    client_id = os.environ.get("PLAID_CLIENT_ID")
    secret = os.environ.get("PLAID_SECRET")
    if not client_id or not secret:
        sys.exit("Set PLAID_CLIENT_ID and PLAID_SECRET environment variables first.")

    config = plaid.Configuration(
        host=plaid.Environment.Sandbox,
        api_key={"clientId": client_id, "secret": secret},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(config))


def get_access_token(client):
    # 1. Fake bank login (in production this public_token comes from Plaid Link).
    public_token = client.sandbox_public_token_create(
        SandboxPublicTokenCreateRequest(
            institution_id=SANDBOX_BANK,
            initial_products=[Products("transactions")],
            options=SandboxPublicTokenCreateRequestOptions(
                override_username=TEST_USER,
                override_password="pass_good",
            ),
        )
    ).public_token

    # 2. Trade it for an access token. In production, this is the key to someone's
    #    bank data: store it encrypted on your server, never send it to the phone.
    return client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    ).access_token


def sync_all(client, access_token):
    """Call /transactions/sync until has_more is False. Returns (added, cursor)."""
    cursor = ""
    added = []
    while True:
        resp = client.transactions_sync(
            TransactionsSyncRequest(access_token=access_token, cursor=cursor, count=500)
        )
        added.extend(resp.added)
        cursor = resp.next_cursor
        if not resp.has_more:
            return added, cursor


def fetch_transactions(client, access_token, attempts=10, wait_seconds=3):
    # 3. A brand-new Item can take a few seconds before transactions are ready,
    #    so an empty first result means "wait and try again", not "no data".
    for attempt in range(1, attempts + 1):
        try:
            added, _ = sync_all(client, access_token)
        except plaid.ApiException as e:
            body = json.loads(e.body or "{}")
            # Data changed while we were paging: Plaid says to restart from scratch.
            if body.get("error_code") == "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION":
                continue
            raise
        if added:
            return added
        print(f"No transactions yet (attempt {attempt}/{attempts}), waiting {wait_seconds}s...")
        time.sleep(wait_seconds)
    sys.exit("Plaid never returned transactions. Try running the script again.")


def simplify(t):
    t = t.to_dict()
    # Plaid sign convention: positive amount = money LEAVING the account.
    pfc = t.get("personal_finance_category")
    return {
        "transaction_id": t["transaction_id"],
        "date": str(t["date"]),
        "name": t["name"],
        "merchant_name": t.get("merchant_name"),
        "amount": float(t["amount"]),
        "account_id": t["account_id"],
        "category": pfc["primary"] if pfc else None,
        "pending": t.get("pending", False),
    }


def main():
    client = make_client()
    access_token = get_access_token(client)
    raw = fetch_transactions(client, access_token)

    # 4. Save a simplified version, oldest first, skipping pending charges
    #    (they can still change or disappear).
    txns = sorted((simplify(t) for t in raw), key=lambda t: t["date"])
    txns = [t for t in txns if not t["pending"]]
    with open(OUTPUT_FILE, "w") as f:
        json.dump(txns, f, indent=2)
    print(f"Saved {len(txns)} transactions to {OUTPUT_FILE} "
          f"({txns[0]['date']} to {txns[-1]['date']}).")


if __name__ == "__main__":
    main()
