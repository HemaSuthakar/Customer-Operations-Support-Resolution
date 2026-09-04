from fastapi.testclient import TestClient

from app import app, retrieve

client = TestClient(app)


def test_health_and_customer_lookup():
    assert client.get('/api/health').json()['status'] == 'ok'
    response = client.get('/api/customers/CUST-1001')
    assert response.status_code == 200
    assert response.json()['name'] == 'Arun Kumar'


def test_unknown_customer_and_bad_id():
    assert client.get('/api/customers/CUST-9999').status_code == 404
    response = client.post('/api/analyze', json={'customer_id': 'bad', 'conversation': [{'role': 'customer', 'message': 'hello'}]})
    assert response.status_code == 422


def test_normal_case_is_grounded_and_cited():
    response = client.post('/api/analyze', json={'customer_id': 'CUST-1001', 'conversation': [{'role': 'customer', 'message': 'My broadband is not working. It affects my laptop and phone, and the router internet light is red.'}]})
    body = response.json()
    assert body['classification'] == 'RESOLVABLE'
    assert body['citations']
    assert all(item['article_id'].startswith('SA-') for item in body['citations'])


def test_ambiguous_case_requests_only_missing_details():
    body = client.post('/api/analyze', json={'customer_id': 'CUST-1001', 'conversation': [{'role': 'customer', 'message': "My internet isn't working."}]}).json()
    assert body['classification'] == 'NEEDS_INFORMATION'
    assert len(body['missing_information']) == 2


def test_repeated_case_escalates_with_handoff():
    body = client.post('/api/analyze', json={'customer_id': 'CUST-1007', 'conversation': [{'role': 'customer', 'message': 'My broadband keeps dropping again. I restarted the router multiple times and this is my third ticket.'}]}).json()
    assert body['classification'] == 'ESCALATE'
    assert body['handoff']['escalate'] is True


def test_contradiction_is_not_silently_resolved():
    body = client.post('/api/analyze', json={'customer_id': 'CUST-1008', 'conversation': [{'role': 'customer', 'message': 'I already paid my bill but my account says overdue.'}]}).json()
    assert body['classification'] == 'ESCALATE'
    assert 'conflicts' in body['escalation_reason']


def test_unsupported_request_escalates_and_no_match_is_safe():
    body = client.post('/api/analyze', json={'customer_id': 'CUST-1001', 'conversation': [{'role': 'customer', 'message': 'I need a legal contract interpretation for my dispute.'}]}).json()
    assert body['classification'] == 'ESCALATE'
    assert body['citations'] == []
    assert retrieve('quantum telescope ownership') == []


def test_empty_message_rejected():
    response = client.post('/api/analyze', json={'customer_id': 'CUST-1001', 'conversation': [{'role': 'customer', 'message': ''}]})
    assert response.status_code == 422
