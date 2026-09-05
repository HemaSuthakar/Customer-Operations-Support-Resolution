const state = { customers: [], selected: null, messages: [] };
const $ = (id) => document.getElementById(id);

function applyTheme(theme) {
  const dark = theme === 'dark';
  document.body.classList.toggle('theme-dark', dark);
  const toggle = $('themeToggle');
  if (toggle) {
    toggle.textContent = dark ? 'Light mode' : 'Dark mode';
    toggle.setAttribute('aria-pressed', String(dark));
  }
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || 'Request failed');
  return body;
}

function statusText(value) { return value.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase()); }
function showToast(message) { const toast = $('toast'); toast.textContent = message; toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 2600); }

function updateMetrics() {
  const queue = state.customers.length || 0;
  const selected = state.selected?.account_status || 'active';
  $('metricQueue').textContent = queue;
  $('metricNeeds').textContent = selected === 'active' ? '2' : '1';
  $('metricEscalations').textContent = selected === 'suspended' ? '3' : '1';
  $('metricResolved').textContent = Math.max(8, Math.min(96, queue * 4));
}

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
  updateMetrics();
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
  const activeStatus = result.classification === 'ESCALATE' ? 'escalation' : result.classification === 'NEEDS_INFORMATION' ? 'needs-info' : 'resolved';
  $('metricNeeds').textContent = activeStatus === 'needs-info' ? '1' : '2';
  $('metricEscalations').textContent = activeStatus === 'escalation' ? '1' : '0';
  $('metricResolved').textContent = activeStatus === 'resolved' ? '22' : '14';
}

async function analyze() {
  if (!state.selected) return showToast('Select a customer first');
  const message = $('messageInput').value.trim(); if (!message) return showToast('Enter the customer message first');
  state.messages = [{ role: 'customer', message }]; renderConversation();
  const button = $('analyzeButton'); button.disabled = true; button.querySelector('span').textContent = 'Reviewing...';
  try { renderAnalysis(await api('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ customer_id: state.selected.customer_id, conversation: state.messages }) })); } catch (error) { showToast(error.message); } finally { button.disabled = false; button.querySelector('span').textContent = 'Analyze case'; }
}

async function loadDemo(customerId, message) { await selectCustomer(customerId); $('messageInput').value = message; await analyze(); }

async function init() {
  const savedTheme = localStorage.getItem('nova-theme') || 'light';
  applyTheme(savedTheme);
  $('themeToggle')?.addEventListener('click', () => {
    const nextTheme = document.body.classList.contains('theme-dark') ? 'light' : 'dark';
    localStorage.setItem('nova-theme', nextTheme);
    applyTheme(nextTheme);
  });

  // Modal controls
  const addBtn = $('addCustomerBtn');
  const modal = $('addCustomerModal');
  const closeBtn = $('closeModal');
  const cancelBtn = $('cancelForm');
  const overlay = document.querySelector('.modal-overlay');
  const form = $('addCustomerForm');

  if (addBtn) {
    addBtn.addEventListener('click', () => {
      if (modal) modal.classList.remove('hidden');
      const nameInput = $('customerName');
      if (nameInput) nameInput.focus();
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      if (modal) modal.classList.add('hidden');
    });
  }

  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      if (modal) modal.classList.add('hidden');
      if (form) form.reset();
    });
  }

  if (overlay) {
    overlay.addEventListener('click', () => {
      if (modal) modal.classList.add('hidden');
    });
  }

  // Handle form submission
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const button = form.querySelector('button[type="submit"]');
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = 'Creating...';
      try {
        const newCustomer = await api('/api/customers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: $('customerName').value,
            service_type: $('serviceType').value,
            plan: $('plan').value,
            billing_status: $('billingStatus').value,
            account_status: $('accountStatus').value,
            service_status: $('serviceStatus').value,
          })
        });
        state.customers.push(newCustomer);
        renderCustomers();
        $('customerCount').textContent = state.customers.length;
        if (modal) modal.classList.add('hidden');
        form.reset();
        showToast(`Customer ${newCustomer.customer_id} created successfully`);
      } catch (error) {
        showToast(error.message);
      } finally {
        button.disabled = false;
        button.textContent = originalText;
      }
    });
  }

  state.customers = await api('/api/customers');
  $('customerCount').textContent = state.customers.length;
  renderCustomers();
  $('customerSearch').addEventListener('input', e => renderCustomers(e.target.value));
  $('analyzeButton').addEventListener('click', analyze);
  $('demoNormal').addEventListener('click', () => loadDemo('CUST-1001', 'My broadband is not working. It affects my laptop and phone, and the router internet light is red.'));
  $('demoEscalation').addEventListener('click', () => loadDemo('CUST-1007', 'My broadband keeps dropping again. I have restarted the router multiple times and this is my third ticket.'));
}
init().catch(error => showToast(error.message));
