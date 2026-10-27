"""
Unbusy API: connect a bank through Plaid and get the user's subscriptions back.

    pip install -r requirements.txt
    export PLAID_CLIENT_ID=...  PLAID_SECRET=...     (only needed for the /link routes)
    uvicorn api:app --reload

Interactive docs at http://127.0.0.1:8000/docs

Flow for the app:
    POST /link/token      -> link_token, used to open the Plaid pop-up in the app
    POST /link/exchange   -> app sends the public_token from the pop-up, gets a connection_id
    GET  /subscriptions/{connection_id} -> the "You're paying $X/month" screen

For testing without the app:
    POST /link/sandbox    -> fake bank login, returns a connection_id
    POST /analyze         -> send transactions as JSON, no Plaid needed
"""

import json
import secrets
from datetime import date
from typing import Optional

import plaid
from fastapi import FastAPI, HTTPException
from plaid.model.country_code import CountryCode
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from pydantic import BaseModel

import fetch_transactions as plaid_fetch
from detect_recurring import detect, summarize

app = FastAPI(title="Unbusy API", version="0.1.0")

# connection_id -> Plaid access token.
# PROTOTYPE ONLY: this is lost on restart and has no login. In production, store
# access tokens encrypted in Postgres, tied to an authenticated user, and never
# send them to the phone. The app only ever sees the connection_id.
CONNECTIONS: dict[str, str] = {}

_client = None


def plaid_client():
    # Created on first use so /analyze works without Plaid keys.
    global _client
    if _client is None:
        try:
            _client = plaid_fetch.make_client()
        except RuntimeError as e:
            raise HTTPException(503, str(e))
    return _client


def plaid_error(e: plaid.ApiException):
    body = json.loads(e.body or "{}")
    return HTTPException(502, {"plaid_error": body.get("error_code"),
                               "message": body.get("error_message")})


# ---------- Models ----------

class Transaction(BaseModel):
    transaction_id: Optional[str] = None
    date: date                      # YYYY-MM-DD
    name: str
    merchant_name: Optional[str] = None
    amount: float                   # positive = money leaving the account
    account_id: Optional[str] = None
    category: Optional[str] = None
    pending: bool = False


class Subscription(BaseModel):
    merchant: str
    display_name: str
    cadence: str
    usual_amount: float
    latest_amount: float
    monthly_cost: float
    charge_count: int
    first_charge: str
    last_charge: str
    next_expected: Optional[str]
    status: str
    price_increase: bool


class Summary(BaseModel):
    monthly_total: float
    yearly_total: float
    active_count: int
    price_increases: list[str]


class SubscriptionsResponse(BaseModel):
    summary: Summary
    subscriptions: list[Subscription]


class AnalyzeRequest(BaseModel):
    transactions: list[Transaction]


class LinkTokenRequest(BaseModel):
    user_id: str


class ExchangeRequest(BaseModel):
    public_token: str


class Connection(BaseModel):
    connection_id: str


def build_response(transactions: list[dict]) -> SubscriptionsResponse:
    results = detect(transactions)
    return SubscriptionsResponse(summary=summarize(results), subscriptions=results)


def save_connection(public_token: str) -> Connection:
    try:
        access_token = plaid_fetch.exchange_public_token(plaid_client(), public_token)
    except plaid.ApiException as e:
        raise plaid_error(e)
    connection_id = secrets.token_urlsafe(16)
    CONNECTIONS[connection_id] = access_token
    return Connection(connection_id=connection_id)


# ---------- Routes ----------

@app.get("/health")
def health():
    return {"ok": True}


@app.post("/link/token")
def create_link_token(req: LinkTokenRequest):
    """Step 1 in the real app: get a link_token to open the Plaid pop-up."""
    try:
        resp = plaid_client().link_token_create(LinkTokenCreateRequest(
            user=LinkTokenCreateRequestUser(client_user_id=req.user_id),
            client_name="Unbusy",
            products=[Products("transactions")],
            country_codes=[CountryCode("US")],
            language="en",
        ))
    except plaid.ApiException as e:
        raise plaid_error(e)
    return {"link_token": resp.link_token, "expiration": str(resp.expiration)}


@app.post("/link/exchange", response_model=Connection)
def exchange(req: ExchangeRequest):
    """Step 2 in the real app: trade the pop-up's public_token for a stored connection."""
    return save_connection(req.public_token)


@app.post("/link/sandbox", response_model=Connection)
def sandbox_link():
    """Testing shortcut: fake bank login with the user_transactions_dynamic test user."""
    try:
        public_token = plaid_fetch.create_sandbox_public_token(plaid_client())
    except plaid.ApiException as e:
        raise plaid_error(e)
    return save_connection(public_token)


@app.get("/subscriptions/{connection_id}", response_model=SubscriptionsResponse)
def get_subscriptions(connection_id: str):
    """Pull the latest transactions from Plaid and find the subscriptions."""
    access_token = CONNECTIONS.get(connection_id)
    if not access_token:
        raise HTTPException(404, "Unknown connection_id. Link a bank first.")
    try:
        transactions = plaid_fetch.get_transactions(plaid_client(), access_token)
    except plaid.ApiException as e:
        raise plaid_error(e)
    except RuntimeError as e:  # Plaid still preparing data for a new account
        raise HTTPException(503, str(e))
    return build_response(transactions)


@app.post("/analyze", response_model=SubscriptionsResponse)
def analyze(req: AnalyzeRequest):
    """Run the detector on transactions you send. No Plaid needed."""
    return build_response([t.model_dump(mode="json") for t in req.transactions])
