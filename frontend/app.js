const state = { customers: [], selected: null, messages: [] };
const $ = (id) => document.getElementById(id);

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || 'Request failed');
  return body;
}

function statusText(value) { return value.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase()); }
function showToast(message) { const toast = $('toast'); toast.textContent = message; toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 2600); }

function renderCustomers(filter = '') {
  const term = filter.toLowerCase();
  const list = state.customers.filter(item => `${item.name} ${item.customer_id} ${item.plan}`.toLowerCase().includes(term));
  $('customerList').innerHTML = list.map(item => `<div class="customer-item ${state.selected?.customer_id === item.customer_id ? 'active' : ''}" data-id="${item.customer_id}"><div class="customer-primary"><span>${item.name}</span><span class="status-dot"></span></div><div class="customer-secondary">${item.customer_id} · ${item.plan}</div></div>`).join('') || '<div class="conversation-empty">No matching customer.</div>';
  document.querySelectorAll('.customer-item').forEach(node => node.addEventListener('click', () => selectCustomer(node.dataset.id)));
}

async function selectCustomer(id) {
  state.selected = await api(`/api/customers/${id}`);
  state.messages = [];
  renderCustomers($('customerSearch').value);
  $('caseTitle').textContent = `${state.selected.name}'s case`;
  $('accountStrip').classList.remove('empty-state');
  $('accountStrip').innerHTML = `<div class="account-grid"><div class="account-cell"><label>Customer ID</label><strong>${state.selected.customer_id}</strong></div><div class="account-cell"><label>Service</label><strong>${statusText(state.selected.service_type)}</strong></div><div class="account-cell"><label>Plan</label><strong>${state.selected.plan}</strong></div><div class="account-cell"><label>Billing</label><strong class="${state.selected.billing_status === 'paid' ? 'ok' : ''}">${statusText(state.selected.billing_status)}</strong></div><div class="account-cell"><label>Account</label><strong class="ok">${statusText(state.selected.account_status)}</strong></div></div>`;
  const tickets = state.selected.recent_tickets || [];
  $('conversationHistory').innerHTML = `<div class="conversation-empty">${tickets.length ? `${tickets.length} recent ticket${tickets.length > 1 ? 's' : ''} on file · latest: ${tickets[0].issue}` : 'No recent support tickets found.'}</div>`;
  $('messageInput').focus();
  $('analysisPanel').classList.add('hidden'); $('analysisEmpty').classList.remove('hidden');
}

function renderConversation() {
  $('conversationHistory').innerHTML = state.messages.map(item => `<div class="message"><div class="message-avatar">C</div><div class="message-body"><span class="message-label">Customer reported</span>${item.message}</div></div>`).join('');
}

function renderAnalysis(result) {
  const cls = result.classification === 'RESOLVABLE' ? 'status-resolvable' : result.classification === 'NEEDS_INFORMATION' ? 'status-needs' : 'status-escalate';
  const statusLabel = result.classification === 'ESCALATE' ? 'Human escalation' : result.classification === 'NEEDS_INFORMATION' ? 'Needs information' : 'Resolvable';
  const citations = result.citations.length ? result.citations.map(item => `<div class="evidence-item"><div class="evidence-head"><span class="evidence-id">${item.article_id} · ${item.section}</span><span class="score">match ${Math.round(item.score * 100)}%</span></div><div class="evidence-title">${item.title}</div><div class="evidence-content">${item.content}</div><span class="citation-tag">Citation · ${item.article_id}</span></div>`).join('') : '<div class="conversation-empty">No support evidence passed the relevance threshold.</div>';
  const missing = result.missing_information.length ? `<div class="analysis-block"><div class="block-label">Information needed</div><ul class="missing-list">${result.missing_information.map(item => `<li>${item}</li>`).join('')}</ul></div>` : '';
  const handoff = result.handoff ? `<div class="analysis-block full-width handoff"><div class="block-label">Human handoff required</div><p class="block-text"><strong>${result.handoff.reason}</strong></p><ul class="handoff-list">${result.handoff.established_facts.map(item => `<li>${item}</li>`).join('')} ${result.handoff.attempted_steps.map(item => `<li>Attempted: ${item}</li>`).join('')}</ul></div>` : '';
  $('analysisPanel').innerHTML = `<div class="analysis-top"><div><span class="eyebrow">AI REVIEW · GROUNDED</span><h3 class="analysis-title">${result.issue_summary}</h3><p class="analysis-subtitle">${result.retrieval_note}</p></div><span class="status-badge ${cls}">${statusLabel}</span></div><div class="analysis-grid"><div class="analysis-block"><div class="block-label">Customer reported</div><p class="block-text">${result.customer_reported.join('<br>')}</p></div><div class="analysis-block"><div class="block-label">Account record</div><p class="block-text">${result.account_facts.join('<br>')}</p></div><div class="analysis-block recommendation ${result.resolution_draft ? '' : 'full-width'}"><div class="block-label">Recommended action</div><p class="block-text">${result.recommended_action}</p>${result.resolution_draft ? `<div class="block-label" style="margin-top:16px">Resolution draft <button class="copy-button" id="copyDraft">Copy draft</button></div><div class="draft-box" id="draftText">${result.resolution_draft}</div>` : ''}</div>${missing}<div class="analysis-block full-width"><div class="block-label">Retrieved evidence · citations</div><div class="evidence-list">${citations}</div></div>${handoff}<div class="analysis-block full-width"><div class="block-label">Reasoning</div><p class="block-text">${result.reasoning}</p></div></div>`;
  $('analysisEmpty').classList.add('hidden'); $('analysisPanel').classList.remove('hidden');
  const copy = $('copyDraft'); if (copy) copy.addEventListener('click', () => { navigator.clipboard.writeText($('draftText').textContent); showToast('Draft copied to clipboard'); });
}

async function analyze() {
  if (!state.selected) return showToast('Select a customer first');
  const message = $('messageInput').value.trim(); if (!message) return showToast('Enter the customer message first');
  state.messages = [{ role: 'customer', message }]; renderConversation();
  const button = $('analyzeButton'); button.disabled = true; button.querySelector('span').textContent = 'Reviewing...';
  try { renderAnalysis(await api('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ customer_id: state.selected.customer_id, conversation: state.messages }) })); } catch (error) { showToast(error.message); } finally { button.disabled = false; button.querySelector('span').textContent = 'Analyze case'; }
}

async function loadDemo(customerId, message) { await selectCustomer(customerId); $('messageInput').value = message; await analyze(); }

async function init() { state.customers = await api('/api/customers'); $('customerCount').textContent = state.customers.length; renderCustomers(); $('customerSearch').addEventListener('input', e => renderCustomers(e.target.value)); $('analyzeButton').addEventListener('click', analyze); $('demoNormal').addEventListener('click', () => loadDemo('CUST-1001', 'My broadband is not working. It affects my laptop and phone, and the router internet light is red.')); $('demoEscalation').addEventListener('click', () => loadDemo('CUST-1007', 'My broadband keeps dropping again. I have restarted the router multiple times and this is my third ticket.')); }
init().catch(error => showToast(error.message));
