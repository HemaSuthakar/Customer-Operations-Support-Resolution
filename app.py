from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).parent
DATA = ROOT / "data"
FRONTEND = ROOT / "frontend"


def load_json(name: str) -> Any:
    with (DATA / name).open(encoding="utf-8") as handle:
        return json.load(handle)


CUSTOMERS = {item["customer_id"]: item for item in load_json("customers.json")}
ARTICLES = load_json("articles.json")
CONVERSATIONS = load_json("conversations.json")

STOP_WORDS = {
    "a", "an", "and", "are", "be", "can", "could", "for", "has", "have", "i",
    "in", "is", "it", "my", "of", "on", "or", "please", "the", "this", "to", "was", "with",
}


def tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP_WORDS and len(word) > 2}


def article_text(article: dict[str, Any]) -> str:
    return " ".join([
        article["title"], article["category"], article["problem_description"],
        " ".join(article["symptoms"]), " ".join(article["applicable_conditions"]),
        " ".join(article["troubleshooting_steps"]), article["resolution"],
        " ".join(article["escalation_conditions"]), " ".join(article["required_information"]),
    ])


ARTICLE_TOKENS = {article["article_id"]: tokens(article_text(article)) for article in ARTICLES}


def cosine_keyword_score(query: str, article: dict[str, Any]) -> float:
    query_tokens = tokens(query)
    target = ARTICLE_TOKENS[article["article_id"]]
    if not query_tokens or not target:
        return 0.0
    overlap = len(query_tokens & target)
    # A small phrase boost makes precise issue terms beat broad category matches.
    score = overlap / math.sqrt(len(query_tokens) * len(target))
    lowered = query.lower()
    title_terms = tokens(article["title"])
    score += 0.14 * len(query_tokens & title_terms) / max(1, len(title_terms))
    for phrase in ("no internet", "slow internet", "mobile data", "payment overdue", "duplicate charge"):
        if phrase in lowered and phrase in article_text(article).lower():
            score += 0.12
    return min(score, 1.0)


def retrieve(query: str, limit: int = 4) -> list[dict[str, Any]]:
    ranked = sorted(
        ((cosine_keyword_score(query, article), article) for article in ARTICLES),
        key=lambda pair: pair[0], reverse=True,
    )
    results = []
    for score, article in ranked[:limit]:
        if score < 0.095:
            continue
        results.append({
            "article_id": article["article_id"],
            "title": article["title"],
            "category": article["category"],
            "section": "Procedure",
            "chunk_id": f'{article["article_id"]}-CHUNK-01',
            "score": round(score, 3),
            "source": f'data/articles.json#{article["article_id"]}',
            "content": article["resolution"] + " " + " ".join(article["troubleshooting_steps"]),
            "required_information": article["required_information"],
            "escalation_conditions": article["escalation_conditions"],
        })
    return results


def gemini_generate(prompt: str) -> str | None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=" + key
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            body = json.loads(response.read())
        return body["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None


class Message(BaseModel):
    role: Literal["customer", "agent", "system"] = "customer"
    message: str = Field(min_length=1, max_length=2000)


class AnalyzeRequest(BaseModel):
    customer_id: str = Field(min_length=3, max_length=30)
    conversation: list[Message] = Field(min_length=1, max_length=30)

    @field_validator("customer_id")
    @classmethod
    def valid_customer_id(cls, value: str) -> str:
        if not re.fullmatch(r"CUST-\d{4}", value.upper()):
            raise ValueError("Customer ID must look like CUST-1001")
        return value.upper()


class Citation(BaseModel):
    article_id: str
    title: str
    section: str
    chunk_id: str
    score: float
    content: str


class AnalyzeResponse(BaseModel):
    classification: Literal["RESOLVABLE", "NEEDS_INFORMATION", "ESCALATE"]
    issue_summary: str
    customer_reported: list[str]
    account_facts: list[str]
    missing_information: list[str]
    recommended_action: str
    resolution_draft: str | None
    reasoning: str
    citations: list[Citation]
    escalation: bool
    escalation_reason: str | None = None
    handoff: dict[str, Any] | None = None
    retrieval_note: str


def facts_for(customer: dict[str, Any]) -> list[str]:
    facts = [
        f'Plan: {customer["plan"]}',
        f'Billing: {customer["billing_status"].replace("_", " ").title()}',
        f'Account: {customer["account_status"].title()}',
        f'Service: {customer["service_status"].title()}',
    ]
    if customer.get("last_payment_date"):
        facts.append(f'Last payment recorded: {customer["last_payment_date"]}')
    return facts


def conversation_text(messages: list[Message]) -> str:
    return "\n".join(f"{message.role}: {message.message}" for message in messages)


def detect_contradiction(text: str, customer: dict[str, Any]) -> bool:
    return customer["billing_status"] in {"overdue", "payment_failed"} and any(
        term in text.lower() for term in ("paid", "payment made", "already paid", "payment went through")
    )


def build_handoff(customer: dict[str, Any], summary: str, missing: list[str], evidence: list[dict[str, Any]], reason: str, messages: list[Message]) -> dict[str, Any]:
    attempted = [m.message for m in messages if m.role == "customer" and any(
        term in m.message.lower() for term in ("restarted", "reset", "tried", "already checked", "replaced")
    )]
    return {
        "escalate": True,
        "reason": reason,
        "summary": summary,
        "established_facts": facts_for(customer),
        "attempted_steps": attempted or ["No completed troubleshooting step was recorded."],
        "missing_information": missing,
        "relevant_evidence": [{"article_id": item["article_id"], "title": item["title"], "section": item["section"]} for item in evidence],
    }


def fallback_draft(customer: dict[str, Any], evidence: list[dict[str, Any]], contradiction: bool) -> str:
    if contradiction:
        return "I can see a difference between the payment information you provided and the account record. Please confirm the payment date and reference so a support agent can verify it before any account action is taken."
    steps = evidence[0]["content"] if evidence else "Please provide more details so we can identify the correct support procedure."
    return f"Thanks for reporting this. Our records show that your account is {customer['account_status']} and your billing status is {customer['billing_status'].replace('_', ' ')}. Based on the applicable support procedure: {steps} We have not changed your account or performed any action."


def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    customer = CUSTOMERS.get(request.customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    text = conversation_text(request.conversation)
    lowered = text.lower()
    contradiction = detect_contradiction(text, customer)
    query = f"{text} service {customer['service_type']} plan {customer['plan']} billing {customer['billing_status']}"
    evidence = retrieve(query)
    unsupported = any(term in lowered for term in ("legal contract", "lawsuit", "legal interpretation", "court"))
    complex_case = len(customer.get("recent_tickets", [])) >= 3 and any(term in lowered for term in ("again", "still", "repeated", "already tried", "multiple times"))
    missing: list[str] = []
    issue_summary = "Customer support request"
    if any(term in lowered for term in ("slow", "speed", "buffer")):
        issue_summary = "Broadband speed or performance issue"
    elif any(term in lowered for term in ("not working", "isn't working", "isnt working", "disconnected", "offline", "no internet")):
        issue_summary = "Broadband connectivity issue"
    elif any(term in lowered for term in ("mobile data", "cellular data")):
        issue_summary = "Mobile data connectivity issue"
    elif any(term in lowered for term in ("charge", "bill", "payment", "overdue")):
        issue_summary = "Billing or payment issue"
    if not text.strip():
        raise HTTPException(status_code=422, detail="Conversation message cannot be empty")
    if issue_summary == "Broadband connectivity issue":
        if not any(term in lowered for term in ("all devices", "every device", "phone and laptop", "laptop and phone", "one device", "both devices")):
            missing.append("Whether the problem affects all devices or only one device")
        if not any(term in lowered for term in ("router light", "internet light", "indicator", "red light", "light is", "lights")):
            missing.append("The current router or modem indicator-light status")
    if issue_summary == "Mobile data connectivity issue" and not any(term in lowered for term in ("signal", "coverage", "restart", "apn")):
        missing.append("The phone model and whether calls or signal are also affected")
    if contradiction:
        missing = ["Payment date and payment reference or receipt"]
    if unsupported:
        reason = "The request is outside the available broadband and mobile support procedures."
        handoff = build_handoff(customer, issue_summary, [], evidence, reason, request.conversation)
        return AnalyzeResponse(classification="ESCALATE", issue_summary=issue_summary, customer_reported=[m.message for m in request.conversation if m.role == "customer"], account_facts=facts_for(customer), missing_information=[], recommended_action="Route to a human support agent for review.", resolution_draft=None, reasoning="No applicable support procedure was found for this request; the assistant will not infer legal or policy guidance.", citations=[], escalation=True, escalation_reason=reason, handoff=handoff, retrieval_note="No applicable article was selected.")
    if not evidence:
        reason = "No relevant support procedure was found in the available knowledge base."
        handoff = build_handoff(customer, issue_summary, [], [], reason, request.conversation)
        return AnalyzeResponse(classification="ESCALATE", issue_summary=issue_summary, customer_reported=[m.message for m in request.conversation if m.role == "customer"], account_facts=facts_for(customer), missing_information=[], recommended_action="Escalate for human investigation.", resolution_draft=None, reasoning="Retrieval returned no evidence above the relevance threshold, so no recommendation was generated.", citations=[], escalation=True, escalation_reason=reason, handoff=handoff, retrieval_note=reason)
    if contradiction:
        reason = "Customer-provided payment information conflicts with the account billing record."
        handoff = build_handoff(customer, issue_summary, missing, evidence, reason, request.conversation)
        citations = [Citation(**item) for item in evidence[:1]]
        return AnalyzeResponse(classification="ESCALATE", issue_summary=issue_summary, customer_reported=[m.message for m in request.conversation if m.role == "customer"], account_facts=facts_for(customer), missing_information=missing, recommended_action="Verify the payment before changing account status.", resolution_draft=None, reasoning="The contradiction must be resolved by verifying the payment; the assistant will not choose between conflicting sources.", citations=citations, escalation=True, escalation_reason=reason, handoff=handoff, retrieval_note=f"{len(evidence)} relevant article(s) retrieved.")
    if complex_case:
        reason = "Repeated troubleshooting is recorded and the case needs human investigation."
        handoff = build_handoff(customer, issue_summary, missing, evidence, reason, request.conversation)
        return AnalyzeResponse(classification="ESCALATE", issue_summary=issue_summary, customer_reported=[m.message for m in request.conversation if m.role == "customer"], account_facts=facts_for(customer), missing_information=missing, recommended_action="Escalate to network support with the attached handoff.", resolution_draft=None, reasoning="The account history and repeated attempts make a routine scripted response insufficient.", citations=[Citation(**item) for item in evidence[:2]], escalation=True, escalation_reason=reason, handoff=handoff, retrieval_note=f"{len(evidence)} relevant article(s) retrieved.")
    if missing:
        return AnalyzeResponse(classification="NEEDS_INFORMATION", issue_summary=issue_summary, customer_reported=[m.message for m in request.conversation if m.role == "customer"], account_facts=facts_for(customer), missing_information=missing, recommended_action="Ask only for the missing diagnostic details before selecting the next procedure.", resolution_draft="To continue, please confirm: " + "; ".join(missing) + ".", reasoning="A relevant procedure exists, but its required diagnostic conditions are not present in the conversation.", citations=[Citation(**item) for item in evidence[:2]], escalation=False, escalation_reason=None, handoff=None, retrieval_note=f"{len(evidence)} relevant article(s) retrieved.")
    draft = fallback_draft(customer, evidence, False)
    prompt = f"Write a concise customer support draft using only the supplied evidence. Do not claim actions were performed. Customer/account facts: {facts_for(customer)}. Evidence: {evidence}. Conversation: {text}"
    generated = gemini_generate(prompt)
    if generated:
        draft = generated
    return AnalyzeResponse(classification="RESOLVABLE", issue_summary=issue_summary, customer_reported=[m.message for m in request.conversation if m.role == "customer"], account_facts=facts_for(customer), missing_information=[], recommended_action=evidence[0]["content"], resolution_draft=draft, reasoning="The request matches a support procedure and the required diagnostic information is present. Recommendations are limited to retrieved evidence.", citations=[Citation(**item) for item in evidence[:3]], escalation=False, escalation_reason=None, handoff=None, retrieval_note=f"{len(evidence)} relevant article(s) retrieved locally.")


app = FastAPI(title="NovaConnect Resolution Assistant", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "customers": len(CUSTOMERS), "articles": len(ARTICLES), "gemini_configured": bool(os.getenv("GEMINI_API_KEY"))}


@app.get("/api/customers")
def customers() -> list[dict[str, Any]]:
    return [{"customer_id": item["customer_id"], "name": item["name"], "service_type": item["service_type"], "plan": item["plan"], "billing_status": item["billing_status"], "account_status": item["account_status"]} for item in CUSTOMERS.values()]


@app.get("/api/customers/{customer_id}")
def customer(customer_id: str) -> dict[str, Any]:
    item = CUSTOMERS.get(customer_id.upper())
    if not item:
        raise HTTPException(status_code=404, detail="Customer not found")
    return item


@app.get("/api/customers/{customer_id}/tickets")
def tickets(customer_id: str) -> list[dict[str, Any]]:
    item = CUSTOMERS.get(customer_id.upper())
    if not item:
        raise HTTPException(status_code=404, detail="Customer not found")
    return item.get("recent_tickets", [])


@app.get("/api/articles")
def articles() -> list[dict[str, Any]]:
    return [{"article_id": a["article_id"], "title": a["title"], "category": a["category"]} for a in ARTICLES]


@app.get("/api/evidence/{article_id}")
def evidence(article_id: str) -> dict[str, Any]:
    for article in ARTICLES:
        if article["article_id"] == article_id.upper():
            return article
    raise HTTPException(status_code=404, detail="Article not found")


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze_endpoint(request: AnalyzeRequest) -> AnalyzeResponse:
    return analyze(request)


@app.get("/{path:path}")
def frontend(path: str = ""):
    requested = FRONTEND / (path or "index.html")
    if requested.is_file() and FRONTEND in requested.parents:
        return FileResponse(requested)
    return FileResponse(FRONTEND / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
