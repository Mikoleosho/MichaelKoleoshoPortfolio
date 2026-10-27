# Unbusy: Phase 1 prototype

Finds recurring charges (subscriptions) in a bank account and shows what they cost per month.

| File | What it does |
| --- | --- |
| `fetch_transactions.py` | Step 1: pulls ~6 months of transactions from Plaid Sandbox into `transactions.json` |
| `detect_recurring.py` | Step 2: finds subscriptions, marks stopped ones, flags price increases, writes `recurring.json` |
| `api.py` | FastAPI server that wraps steps 1 and 2 for the app |
| `make_sample_data.py` | Makes fake transactions so you can test step 2 without Plaid keys |

## Try it without Plaid

```bash
python make_sample_data.py
python detect_recurring.py sample_transactions.json
```

## Run against Plaid Sandbox

1. Sign up at https://dashboard.plaid.com and copy your **Sandbox** keys.
2. `pip install -r requirements.txt`
3. `export PLAID_CLIENT_ID=...` and `export PLAID_SECRET=...`
4. `python fetch_transactions.py` and then `python detect_recurring.py`

Note: Plaid amounts are positive when money **leaves** the account.

## Run the API

```bash
pip install -r requirements.txt
uvicorn api:app --reload
```

Open http://127.0.0.1:8000/docs to try every route in the browser.

| Route | What it does |
| --- | --- |
| `POST /link/token` | Body `{"user_id": "..."}`. Returns a `link_token` the app uses to open the Plaid pop-up |
| `POST /link/exchange` | Body `{"public_token": "..."}` from the pop-up. Stores the access token server-side and returns a `connection_id` |
| `POST /link/sandbox` | Testing shortcut: fake bank login, returns a `connection_id` |
| `GET /subscriptions/{connection_id}` | Pulls fresh transactions and returns the summary and subscriptions |
| `POST /analyze` | Body `{"transactions": [...]}`. Runs the detector on your data, no Plaid keys needed |

Example response:

```json
{
  "summary": {"monthly_total": 48.15, "yearly_total": 577.8, "active_count": 4, "price_increases": ["Netflix"]},
  "subscriptions": [{"display_name": "Netflix", "cadence": "monthly", "latest_amount": 17.99, "monthly_cost": 17.99,
                     "status": "active", "price_increase": true, "next_expected": "2026-11-02", "...": "..."}]
}
```

**Prototype limits:** connections are kept in memory, so they're lost on restart, and there is no login, so anyone with a `connection_id` can read that account's subscriptions. Before real users: add authentication, store access tokens encrypted in Postgres, and save Plaid's sync cursor so each refresh only downloads new transactions.

## How detection works

1. **Clean up names**: strips processor prefixes and ID numbers (`SQ *SPOTIFY 8X2Q` becomes `spotify`).
2. **Same amount**: keeps charges within 20% of the merchant's usual amount.
3. **Regular timing**: needs 3 or more charges, and at least two-thirds of the gaps between them must fit weekly, biweekly, monthly, quarterly or yearly.
4. **Still active**: no charge for more than 1.5 cycles means `stopped`, which is left out of the monthly total.

All the thresholds are constants at the top of `detect_recurring.py`.
