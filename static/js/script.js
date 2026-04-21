// script.js — CommunityVoice  (dashboard + analytics)

let allCases = [];
let currentFilter = 'all';
let refreshTimer = null;

// ── Toast ─────────────────────────────────────────────────────────────────────
function showToast(msg, duration = 2800) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), duration);
}

// ── Dashboard: load & render ──────────────────────────────────────────────────
async function loadCases() {
  try {
    const res = await fetch('/api/cases');
    if (res.status === 401) { window.location.href = '/staff/login'; return; }
    allCases = await res.json();
    renderStats(allCases);
    renderCases();
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(loadCases, 30000);
  } catch (e) {
    console.error('loadCases error:', e);
  }
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
  set('s-open',  cases.filter(c => c.status !== 'resolved').length);
  set('s-done',  cases.filter(c => c.status === 'resolved').length);
}

function renderCases() {
  const container = document.getElementById('cases');
  if (!container) return;
  const search = (document.getElementById('search')?.value || '').toLowerCase();

  let filtered = allCases.filter(c => {
    if (currentFilter === 'high') return c.urgency === 'high';
    if (['new','in_progress','resolved'].includes(currentFilter)) return c.status === currentFilter;
    return true;
  });
  if (search) {
    filtered = filtered.filter(c =>
      (c.name||'').toLowerCase().includes(search) ||
      (c.summary||'').toLowerCase().includes(search) ||
      (c.need_type||'').toLowerCase().includes(search)
    );
  }

  if (!filtered.length) {
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">📭</div><p>No cases found</p></div>`;
    return;
  }

  container.innerHTML = filtered.map(c => buildCaseCard(c)).join('');

  // wire up expand toggles
  container.querySelectorAll('.case-expand').forEach(btn => {
    btn.addEventListener('click', () => {
      const detail = btn.closest('.case-card').querySelector('.case-detail');
      const open = detail.classList.toggle('open');
      btn.textContent = open ? '▲ Less' : '▼ Details';
    });
  });

  // wire up status selects
  container.querySelectorAll('.status-sel').forEach(sel => {
    sel.addEventListener('change', () => updateStatus(sel.dataset.id, sel.value));
  });

  // wire up note forms
  container.querySelectorAll('.note-add-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const caseId = btn.dataset.id;
      const input = document.getElementById(`note-input-${caseId}`);
      if (input) addNote(caseId, input);
    });
  });
}

function buildCaseCard(c) {
  const ts = c.timestamp ? new Date(c.timestamp).toLocaleString('en-US', {
    month:'short', day:'numeric', hour:'numeric', minute:'2-digit'
  }) : '—';
  const urgencyClass = c.urgency || 'low';
  const status = c.status || 'new';
  const statusLabel = { new:'New', in_progress:'In Progress', resolved:'Resolved' }[status] || status;
  const langLabels = { en:'EN', es:'ES', fr:'FR', zh:'ZH', ar:'AR' };
  const langLabel = langLabels[c.language] || '';

  // referrals HTML
  let refHtml = '';
  if (c.referrals && c.referrals.length) {
    refHtml = `<div class="referrals-mini">
      <div class="ref-mini-title">📋 AI-suggested referrals</div>
      <div class="ref-mini-list">
        ${c.referrals.map(r => `<div class="ref-mini-item"><strong>${escHtml(r.type)}:</strong> ${escHtml(r.description)}</div>`).join('')}
      </div>
    </div>`;
  }

  // notes HTML
  const notes = c.notes || [];
  const notesHtml = notes.map(n => `
    <div class="note-item">
      ${escHtml(n.text)}
      <div class="note-meta">${n.author || 'Staff'} · ${n.timestamp ? new Date(n.timestamp).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}) : ''}</div>
    </div>`).join('') || '<div style="font-size:12.5px;color:var(--muted);margin-bottom:8px">No notes yet</div>';

  return `
    <div class="case-card">
      <div class="case-card-top">
        <div class="urgency-bar ${urgencyClass}"></div>
        <div class="case-main">
          <div class="case-name">${escHtml(c.name || 'Anonymous')}${langLabel ? ` <span class="lang-tag">${langLabel}</span>` : ''}</div>
          <div class="case-summary">${escHtml(c.summary || '—')}</div>
          <div class="case-meta">
            <span class="tag need">${escHtml((c.need_type||'other').replace(/_/g,' '))}</span>
            <span class="tag urgency-${urgencyClass}">${urgencyClass} urgency</span>
            ${c.follow_up_needed ? '<span class="tag" style="background:#fef3c7;border-color:#fde68a;color:#92400e">Follow-up needed</span>' : ''}
            <span class="tag" style="background:${statusBg(status)};border-color:${statusBorder(status)};color:${statusColor(status)}">${statusLabel}</span>
          </div>
        </div>
        <div class="case-actions">
          <select class="status-sel" data-id="${c.id}">
            <option value="new" ${status==='new'?'selected':''}>New</option>
            <option value="in_progress" ${status==='in_progress'?'selected':''}>In Progress</option>
            <option value="resolved" ${status==='resolved'?'selected':''}>Resolved</option>
          </select>
          <button class="case-expand">▼ Details</button>
        </div>
        <div class="case-time">${ts}</div>
      </div>

      <div class="case-detail">
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

function statusBg(s)     { return {new:'#eff6ff',in_progress:'#fef3c7',resolved:'#d1fae5'}[s]||'#f0ede8'; }
function statusBorder(s) { return {new:'#bfdbfe',in_progress:'#fde68a',resolved:'#6ee7b7'}[s]||'#e5e0d5'; }
function statusColor(s)  { return {new:'#1e40af',in_progress:'#92400e',resolved:'#065f46'}[s]||'#8a8585'; }

async function updateStatus(id, status) {
  try {
    await fetch(`/api/cases/${id}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status })
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
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note })
    });
    const data = await res.json();
    if (data.success) {
      // update in memory
      const c = allCases.find(x => x.id === caseId);
      if (c) {
        if (!c.notes) c.notes = [];
        c.notes.push(data.note);
        // re-render notes list
        const notesList = document.getElementById(`notes-list-${caseId}`);
        if (notesList) {
          const n = data.note;
          const div = document.createElement('div');
          div.className = 'note-item';
          div.innerHTML = `${escHtml(n.text)}<div class="note-meta">${n.author} · ${new Date(n.timestamp).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</div>`;
          notesList.appendChild(div);
        }
      }
      inputEl.value = '';
      showToast('Note added');
    }
  } catch { showToast('Failed to add note'); }
  inputEl.disabled = false;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Analytics ─────────────────────────────────────────────────────────────────
async function loadAnalytics() {
  try {
    const res = await fetch('/api/cases');
    if (res.status === 401) { window.location.href = '/staff/login'; return; }
    allCases = await res.json();
    renderBarChart(allCases);
    renderDonut(allCases);
  } catch (e) { console.error('loadAnalytics error:', e); }
}

function renderBarChart(cases) {
  const counts = {};
  cases.forEach(c => { const n = c.need_type||'other'; counts[n] = (counts[n]||0)+1; });
  const sorted = Object.entries(counts).sort((a,b)=>b[1]-a[1]);
  const max = sorted[0]?.[1]||1;
  const container = document.getElementById('need-chart');
  if (!container) return;
  if (!sorted.length) { container.innerHTML = '<div style="color:var(--muted);font-size:13px">No data yet</div>'; return; }
  const colors = ['#0a2e1e','#1a5c3a','#2ecc8f','#6ee7b7','#a7f3d0','#d1fae5'];
  container.innerHTML = sorted.map(([label,count],i) => `
    <div class="bar-row">
      <div class="bar-label">${escHtml(label.replace(/_/g,' '))}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.round(count/max*100)}%;background:${colors[i%colors.length]}"></div></div>
      <div class="bar-count">${count}</div>
    </div>`).join('');
}

function renderDonut(cases) {
  const high = cases.filter(c=>c.urgency==='high').length;
  const med  = cases.filter(c=>c.urgency==='medium').length;
  const low  = cases.filter(c=>c.urgency==='low').length;
  const total = high+med+low||1;
  const circ = 2*Math.PI*35;
  let offset = 0;
  function arc(count) {
    const dash = `${(count/total*circ).toFixed(1)} ${circ.toFixed(1)}`;
    const off  = (-offset).toFixed(1);
    offset += count/total*circ;
    return { dash, off };
  }
  const h = arc(high), m = arc(med), l = arc(low);
  const set = (id,attr,val) => { const el=document.getElementById(id); if(el) el.setAttribute(attr,val); };
  set('d-high','stroke-dasharray',h.dash); set('d-high','stroke-dashoffset',h.off);
  set('d-med', 'stroke-dasharray',m.dash); set('d-med', 'stroke-dashoffset',m.off);
  set('d-low', 'stroke-dasharray',l.dash); set('d-low', 'stroke-dashoffset',l.off);
  const lbl = document.getElementById('d-label'); if(lbl) lbl.textContent = total;
  const lv = (id,v) => { const el=document.getElementById(id); if(el) el.textContent=v; };
  lv('lv-high',high); lv('lv-med',med); lv('lv-low',low);
}

async function generateInsight() {
  const btn = document.getElementById('genBtn');
  const txt = document.getElementById('aiInsight');
  if (!btn||!txt) return;
  btn.disabled = true; btn.textContent = '✦ Analyzing…';
  txt.textContent = 'Generating AI insights from your case data…';

  const counts = {}; const langCounts = {};
  allCases.forEach(c => {
    const n = c.need_type||'other'; counts[n]=(counts[n]||0)+1;
    const l = c.language||'en'; langCounts[l]=(langCounts[l]||0)+1;
  });
  const topNeed = Object.entries(counts).sort((a,b)=>b[1]-a[1])[0]?.[0]||'unknown';

  try {
    const res = await fetch('/api/analytics/insight', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stats: {
        total: allCases.length,
        high:  allCases.filter(c=>c.urgency==='high').length,
        medium:allCases.filter(c=>c.urgency==='medium').length,
        low:   allCases.filter(c=>c.urgency==='low').length,
        open:  allCases.filter(c=>c.status!=='resolved').length,
        resolved: allCases.filter(c=>c.status==='resolved').length,
        top_need: topNeed, needs: counts, languages: langCounts
      }})
    });
    const data = await res.json();
    txt.textContent = data.insight || 'Could not generate insight.';
  } catch { txt.textContent = 'Unable to connect. Please try again.'; }

  btn.disabled = false; btn.textContent = '✦ Regenerate Insight';
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('cases')) {
    loadCases();
    const searchEl = document.getElementById('search');
    if (searchEl) searchEl.addEventListener('input', renderCases);
  }
  if (document.getElementById('need-chart')) {
    // analytics page — loadAnalytics() called inline in template
  }
});
