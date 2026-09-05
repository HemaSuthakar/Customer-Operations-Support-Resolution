TRACK_ID=PS04

# Customer Support Resolution Assistant

## What the project does

NovaConnect Resolution Desk is a focused support-agent workspace for broadband and mobile cases. It combines a customer conversation, deterministic account facts, and local support procedures to produce a reviewable resolution, a request for only missing information, or a human handoff. It never changes an account or sends a customer message automatically.

## Architecture

A single FastAPI application serves the API and the static dashboard. Synthetic records live in `data/`. Retrieval and classification are deterministic Python logic; Gemini is an optional language layer for polishing a grounded draft when `GEMINI_API_KEY` is configured. The application remains useful without the key through a safe local draft fallback.

## Technology Stack

- Python 3.11+ / FastAPI / Uvicorn
- Pydantic request and response validation
- Vanilla HTML, CSS, and JavaScript dashboard, served by FastAPI
- Local JSON data and in-process keyword vector scoring
- Optional Gemini generation via the Gemini API only

## RAG Pipeline

Articles are loaded from the local JSON knowledge base, normalized into searchable chunks, and ranked locally using cosine-style token overlap with title and phrase boosts. The top four results are filtered by a relevance threshold. Only selected evidence is passed to the optional Gemini prompt; otherwise a deterministic grounded draft is used. No article is retrieved or embedded over a hosted vector database.

The repository is startup-safe: it does not make embedding calls or rebuild an index on startup. In a submission environment with Gemini available, the Gemini path is used for generation; local retrieval and safe fallback keep the demo deterministic and fast.

## Data and Documents

All support articles, conversations, account records, and ticket history are synthetic and created for this project. The dataset contains 10 fictional NovaConnect customers, 15 distinguishable procedures, and demo conversations for normal, ambiguous, and repeated-failure cases.

## How to Run

```text
pip install -r requirements.txt
python app.py
```

Then:

http://localhost:8000

## Environment Variable

`GEMINI_API_KEY`

The key is supplied by the evaluator and is not committed. When present, it is read only from the environment and used for a concise grounded draft. API failures are caught and fall back to the local draft.

## API Endpoints

- `GET /api/health`
- `GET /api/customers`
- `GET /api/customers/{customer_id}`
- `GET /api/customers/{customer_id}/tickets`
- `GET /api/articles`
- `GET /api/evidence/{article_id}`
- `POST /api/analyze`

## Test Cases

Run `python -m pytest -q`. The suite covers health, customer lookup, validation, local retrieval, normal resolution, missing information, unsupported requests, citation presence, contradiction handling, and escalation handoffs.

## Edge Cases

Empty messages and malformed customer IDs are rejected. Unknown customers return a clean 404. Low-relevance retrieval escalates without a recommendation. Contradictory customer and account facts are surfaced. Repeated troubleshooting escalates with the existing context attached. Gemini errors never expose secrets or crash the server.

## Grounding and Citations

Every citation is built from a retrieved article object and includes its article ID, section, score, content, and source. The UI shows the exact evidence used. No citation is generated independently by the model.

## Human Escalation

The handoff includes the reason, issue summary, established account facts, attempted steps, missing information, and relevant retrieved evidence. This means the customer does not need to repeat the case to the next agent.


## Demo scenarios

- Demo A: `CUST-1001` with a known broadband outage symptom and router light detail. The case resolves with `SA-001` evidence and a draft.
- Demo B: `CUST-1007` with three recent tickets and repeated router restarts. The case escalates with a concise handoff.