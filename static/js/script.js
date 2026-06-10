// script.js — CommunityVoice v5 (Round 2)

let allCases = [];
let currentFilter = 'all';
let refreshTimer = null;

function showToast(msg, duration = 2800) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), duration);
}

async function loadCases() {
  try {
    const res = await fetch('/api/cases');
    if (res.status === 401) { window.location.href = '/staff/login'; return; }
    allCases = await res.json();
    renderStats(allCases);
    renderCases();
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(loadCases, 30000);
  } catch(e) { console.error('loadCases error:', e); }
}

function setFilter(f, el) {
  currentFilter = f;
  document.querySelectorAll('.filt-btn').forEach(b => b.classList.remove('active'));
  if (el) el.classList.add('active');
  renderCases();
}

function renderStats(cases) {
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('s-total', cases.length);
  set('s-high',  cases.filter(c => c.urgency === 'high').length);
  set('s-open',  cases.filter(c => c.status !== 'resolved' && c.status !== 'auto_resolved').length);
  set('s-done',  cases.filter(c => c.status === 'resolved').length);
  set('s-auto',  cases.filter(c => c.status === 'auto_resolved' || c.auto_resolved === true).length);
  set('s-review', cases.filter(c => c.needs_review && !c.human_takeover).length);
}

function renderCases() {
  const container = document.getElementById('cases');
  if (!container) return;
  const search = (document.getElementById('search')?.value || '').toLowerCase();

  let filtered = allCases.filter(c => {
    if (currentFilter === 'high')          return c.urgency === 'high';
    if (currentFilter === 'crisis')        return c.crisis_flag || c.is_crisis;
    if (currentFilter === 'auto_resolved') return c.status === 'auto_resolved' || c.auto_resolved;
    if (currentFilter === 'needs_review')  return c.needs_review && !c.human_takeover;
    if (currentFilter === 'thumbs_down')   return c.satisfaction === 'down';
    if (['new','in_progress','resolved'].includes(currentFilter)) return c.status === currentFilter;
    return true;
  });
  if (search) filtered = filtered.filter(c =>
    (c.name||'').toLowerCase().includes(search) ||
    (c.summary||'').toLowerCase().includes(search) ||
    (c.need_type||'').toLowerCase().includes(search)
  );

  if (!filtered.length) {
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">📭</div><p>No cases found</p></div>`;
    return;
  }

  container.innerHTML = filtered.map(buildCaseCard).join('');

  container.querySelectorAll('.expand-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const detail = btn.closest('.case-card').querySelector('.case-detail');
      const open = detail.classList.toggle('open');
      btn.textContent = open ? '▲ Less' : '▼ Details';
    });
  });
  container.querySelectorAll('.status-sel').forEach(sel =>
    sel.addEventListener('change', () => updateStatus(sel.dataset.id, sel.value))
  );
  container.querySelectorAll('.takeover-btn').forEach(btn =>
    btn.addEventListener('click', () => takeoverCase(btn.dataset.id))
  );
  container.querySelectorAll('.note-add-btn').forEach(btn =>
    btn.addEventListener('click', () => {
      const inp = document.getElementById(`note-input-${btn.dataset.id}`);
      if (inp) addNote(btn.dataset.id, inp);
    })
  );
}

const LANG_LABELS = {en:'EN',es:'ES',fr:'FR',zh:'ZH',ar:'AR'};

function buildCaseCard(c) {
  const ts = c.timestamp ? new Date(c.timestamp).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}) : '—';
  const urgency = c.urgency || 'low';
  const status  = c.status  || 'new';
  const isCrisis = c.crisis_flag || c.is_crisis;
  const statusLabel = {new:'New',in_progress:'In Progress',resolved:'Resolved',auto_resolved:'✦ Auto-Resolved'}[status] || status;
  const lang = LANG_LABELS[c.language] || '';

  let refHtml = '';
  if (c.referrals && c.referrals.length) {
    refHtml = `<div class="referrals-mini">
      <div class="ref-mini-title">📋 AI-suggested referrals</div>
      <div class="ref-mini-list">
        ${c.referrals.map(r=>`<div class="ref-mini-item"><strong>${esc(r.type)}:</strong> ${esc(r.description)}</div>`).join('')}
      </div></div>`;
  }

  const notes = c.notes || [];
  const notesHtml = notes.length
    ? notes.map(n=>`<div class="note-item">${esc(n.text)}<div class="note-meta">${n.author||'Staff'} · ${n.timestamp ? new Date(n.timestamp).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}) : ''}</div></div>`).join('')
    : `<div style="font-size:12.5px;color:var(--muted);margin-bottom:8px">No notes yet</div>`;

  const sbg = {new:'#eff6ff',in_progress:'#fef3c7',resolved:'#d1fae5',auto_resolved:'#f0fdf4'}[status]||'#f0ede8';
  const sbo = {new:'#bfdbfe',in_progress:'#fde68a',resolved:'#6ee7b7',auto_resolved:'#86efac'}[status]||'#e5e0d5';
  const sco = {new:'#1e40af',in_progress:'#92400e',resolved:'#065f46',auto_resolved:'#14532d'}[status]||'#8a8585';

  return `<div class="case-card${isCrisis ? ' crisis-card' : ''}">
    <div class="case-card-top">
      <div class="urgency-bar ${urgency}"></div>
      <div class="case-main">
        <div class="case-name">
          ${isCrisis ? '<span style="background:#fee2e2;color:#991b1b;border:1px solid #fecaca;border-radius:20px;padding:2px 8px;font-size:11px;font-weight:700;margin-right:6px">🆘 CRISIS</span>' : ''}
          ${esc(c.name||'Anonymous')}${lang ? `<span class="lang-tag">${lang}</span>` : ''}
        </div>
        <div class="case-summary">${esc(c.summary||'—')}</div>
        <div class="case-meta">
          <span class="tag need">${esc((c.need_type||'other').replace(/_/g,' '))}</span>
          <span class="tag urgency-${urgency}">${urgency} urgency</span>
          ${c.follow_up_needed ? '<span class="tag" style="background:#fef3c7;border-color:#fde68a;color:#92400e">Follow-up needed</span>' : ''}
          <span class="tag" style="background:${sbg};border-color:${sbo};color:${sco}">${statusLabel}</span>
        </div>
      </div>
      <div class="case-actions">
        ${c.satisfaction === 'down' && !c.human_takeover ? `<button class="takeover-btn" data-id="${c.id}">🙋 Take Over</button>` : ''}
        ${c.satisfaction === 'up' ? '<span style="font-size:13px;color:#16a34a" title="User satisfied">👍</span>' : ''}
        ${c.satisfaction === 'down' ? '<span style="font-size:13px;color:#dc2626" title="User not satisfied — needs review">👎</span>' : ''}
        ${c.human_takeover ? '<span style="font-size:11px;background:#fef3c7;border:1px solid #fde68a;color:#92400e;padding:2px 7px;border-radius:20px;font-weight:600">🙋 Human</span>' : ''}
        <select class="status-sel" data-id="${c.id}">
          <option value="new"          ${status==='new'?'selected':''}>New</option>
          <option value="in_progress"  ${status==='in_progress'?'selected':''}>In Progress</option>
          <option value="resolved"     ${status==='resolved'?'selected':''}>Resolved</option>
          <option value="auto_resolved"${status==='auto_resolved'?'selected':''}>✦ Auto-Resolved</option>
        </select>
        <button class="expand-btn">▼ Details</button>
      </div>
      <div class="case-time">${ts}</div>
    </div>
    <div class="case-detail">
      ${isCrisis ? `<div style="background:#fee2e2;border:1px solid #fca5a5;border-radius:10px;padding:12px 16px;margin-top:14px;font-size:13px;color:#7f1d1d">
        <strong>🆘 Crisis case — immediate staff follow-up required.</strong><br>
        Please contact this person directly as soon as possible. Do not leave this case unattended. Resources provided: 988, Crisis Text Line, 911.
      </div>` : ''}
      ${c.auto_resolved && c.resolution_summary ? `<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:10px;padding:12px 16px;margin-top:14px;font-size:13px;color:#14532d">
        <strong>✦ Auto-resolved by AI:</strong> ${esc(c.resolution_summary)}
      </div>` : ''}
      ${refHtml}
      <div class="notes-section">
        <div class="notes-title">📝 Staff notes</div>
        <div id="notes-list-${c.id}">${notesHtml}</div>
        <div class="note-input-row">
          <input class="note-input" id="note-input-${c.id}" type="text" placeholder="Add a note…">
          <button class="note-add-btn" data-id="${c.id}">Add note</button>
        </div>
      </div>
    </div>
  </div>`;
}

async function updateStatus(id, status) {
  try {
    await fetch(`/api/cases/${id}/status`, {
      method: 'PATCH', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({status})
    });
    const c = allCases.find(x => x.id === id);
    if (c) c.status = status;
    renderStats(allCases);
    showToast(`Status → ${status.replace('_',' ')}`);
  } catch { showToast('Failed to update status'); }
}

async function addNote(caseId, inputEl) {
  const note = inputEl.value.trim();
  if (!note) return;
  inputEl.disabled = true;
  try {
    const res = await fetch(`/api/cases/${caseId}/notes`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({note})
    });
    const data = await res.json();
    if (data.success) {
      const c = allCases.find(x => x.id === caseId);
      if (c) { if(!c.notes) c.notes=[]; c.notes.push(data.note); }
      const nl = document.getElementById(`notes-list-${caseId}`);
      if (nl) {
        const n = data.note;
        const d = document.createElement('div'); d.className = 'note-item';
        d.innerHTML = `${esc(n.text)}<div class="note-meta">${n.author} · ${new Date(n.timestamp).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</div>`;
        nl.appendChild(d);
      }
      inputEl.value = ''; showToast('Note added');
    }
  } catch { showToast('Failed to add note'); }
  inputEl.disabled = false;
}

async function takeoverCase(caseId) {
  if (!confirm('Take over this case? You will be assigned as the direct staff contact.')) return;
  try {
    const res = await fetch(`/api/cases/${caseId}/takeover`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({note: 'Staff manually took over after reviewing case.'})
    });
    const data = await res.json();
    if (data.success) {
      const c = allCases.find(x => x.id === caseId);
      if (c) { c.human_takeover = true; c.status = 'in_progress'; c.needs_review = false; }
      renderStats(allCases);
      renderCases();
      showToast('🙋 Case taken over — assigned to you');
    }
  } catch { showToast('Failed to take over case'); }
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('cases')) {
    loadCases();
    const s = document.getElementById('search');
    if (s) s.addEventListener('input', renderCases);
  }
});