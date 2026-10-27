# Unbusy: Phase 1 prototype

Finds recurring charges (subscriptions) in a bank account and shows what they cost per month.

| File | What it does |
| --- | --- |
| `fetch_transactions.py` | Step 1: pulls ~6 months of transactions from Plaid Sandbox into `transactions.json` |
| `detect_recurring.py` | Step 2: finds subscriptions, marks stopped ones, flags price increases, writes `recurring.json` |
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

## How detection works

1. **Clean up names**: strips processor prefixes and ID numbers (`SQ *SPOTIFY 8X2Q` becomes `spotify`).
2. **Same amount**: keeps charges within 20% of the merchant's usual amount.
3. **Regular timing**: needs 3 or more charges, and at least two-thirds of the gaps between them must fit weekly, biweekly, monthly, quarterly or yearly.
4. **Still active**: no charge for more than 1.5 cycles means `stopped`, which is left out of the monthly total.

All the thresholds are constants at the top of `detect_recurring.py`.
