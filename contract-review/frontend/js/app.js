/* ContractReview — Frontend Application */
const API = '';

// ── State ──
let state = {
  documents: [],
  kbEntries: [],
  categories: [],
  currentTab: 'documents',
};

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  checkHealth();
  loadDocuments();
  loadKbEntries();
  loadKbCategories();
  setupTabs();
  setupUpload();
  setupKb();
  setupKbImport();
  setupReview();
  loadReviewDocs();
});

// ── Health Check ──
async function checkHealth() {
  try {
    const res = await fetch(`${API}/api/health`);
    const data = await res.json();
    const badge = document.getElementById('llmStatus');
    if (data.llm_configured) {
      badge.textContent = 'LLM 已就绪';
      badge.className = 'badge badge-success';
    }
  } catch (e) { /* offline */ }
}

// ── Tab Navigation ──
function setupTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      const tab = document.getElementById(`tab-${btn.dataset.tab}`);
      if (tab) tab.classList.add('active');
      state.currentTab = btn.dataset.tab;
    });
  });
}

// ═══════════════════════════════════════════
// DOCUMENTS
// ═══════════════════════════════════════════

function setupUpload() {
  const zone = document.getElementById('uploadZone');
  const fileInput = document.getElementById('fileInput');

  zone.addEventListener('click', () => fileInput.click());
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) uploadFile(fileInput.files[0]);
  });
}

async function uploadFile(file) {
  const progress = document.getElementById('uploadProgress');
  const result = document.getElementById('uploadResult');
  progress.classList.remove('hidden');
  result.classList.add('hidden');

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch(`${API}/api/documents/upload`, { method: 'POST', body: formData });
    const data = await res.json();
    progress.classList.add('hidden');
    if (res.ok) {
      result.innerHTML = `<div class="success">✅ ${data.message}</div>`;
      result.classList.remove('hidden');
      loadDocuments();
      setTimeout(() => result.classList.add('hidden'), 5000);
    } else {
      result.innerHTML = `<div class="error">❌ ${data.detail || '上传失败'}</div>`;
      result.classList.remove('hidden');
    }
  } catch (e) {
    progress.classList.add('hidden');
    result.innerHTML = `<div class="error">❌ 网络错误</div>`;
    result.classList.remove('hidden');
  }
}

async function loadDocuments() {
  try {
    const res = await fetch(`${API}/api/documents`);
    state.documents = await res.json();
    renderDocList();
    loadReviewDocs();
  } catch (e) { /* ignore */ }
}

function renderDocList() {
  const el = document.getElementById('docList');
  if (!state.documents.length) {
    el.innerHTML = '<p class="empty-state">暂无文档，请上传</p>';
    return;
  }

  el.innerHTML = `
    <table>
      <thead><tr>
        <th>文件名</th>
        <th>格式</th>
        <th>条款数</th>
        <th>状态</th>
        <th>上传时间</th>
        <th>操作</th>
      </tr></thead>
      <tbody>
        ${state.documents.map(d => `
          <tr>
            <td>${d.original_name}</td>
            <td><span class="tag tag-${d.file_type}">${d.file_type.toUpperCase()}</span></td>
            <td>${d.clause_count || '-'}</td>
            <td><span class="tag tag-${d.status === 'parsed' ? 'low' : 'mid'}">${statusLabel(d.status)}</span></td>
            <td class="text-muted">${d.created_at}</td>
            <td>
              <button class="btn btn-sm btn-secondary" onclick="viewClauses(${d.id})">查看条款</button>
              <button class="btn btn-sm btn-danger" onclick="deleteDoc(${d.id})">删除</button>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function statusLabel(s) {
  const m = { uploaded: '已上传', parsing: '解析中', parsed: '已解析', error: '解析失败' };
  return m[s] || s;
}

async function viewClauses(docId) {
  try {
    const res = await fetch(`${API}/api/documents/${docId}/clauses`);
    const clauses = await res.json();
    const doc = state.documents.find(d => d.id === docId);
    const html = `
      <div class="panel">
        <h3>📄 ${doc ? doc.original_name : '合同'} — 共 ${clauses.length} 个条款</h3>
        ${clauses.map(c => `
          <div class="annotation-item" style="margin-bottom:6px">
            <strong>第 ${c.clause_index} 条</strong>
            ${c.section_title ? `<span class="text-muted">（${c.section_title}）</span>` : ''}
            <span class="text-muted">第 ${c.page_number} 页</span>
            <div class="clause-text">${c.content.substring(0, 300)}${c.content.length > 300 ? '...' : ''}</div>
          </div>
        `).join('')}
      </div>
    `;
    const win = window.open('', '_blank');
    win.document.write(`<html><head><link rel="stylesheet" href="/css/style.css"><style>body{background:#0f1419;padding:20px;}</style></head><body>${html}</body></html>`);
    win.document.close();
  } catch (e) { alert('加载失败'); }
}

async function deleteDoc(docId) {
  if (!confirm('确定删除此文档？')) return;
  await fetch(`${API}/api/documents/${docId}`, { method: 'DELETE' });
  loadDocuments();
}

// ═══════════════════════════════════════════
// KNOWLEDGE BASE
// ═══════════════════════════════════════════

async function loadKbCategories() {
  try {
    const res = await fetch(`${API}/api/kb/categories`);
    const data = await res.json();
    state.categories = data.categories || [];
    const sel = document.getElementById('kbCategoryFilter');
    state.categories.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c; opt.textContent = c;
      sel.appendChild(opt);
    });
  } catch (e) { /* ignore */ }
}

async function loadKbEntries(category = '', search = '') {
  try {
    let url = `${API}/api/kb/entries`;
    const params = new URLSearchParams();
    if (category) params.set('category', category);
    if (search) params.set('search', search);
    const qs = params.toString();
    if (qs) url += '?' + qs;

    const res = await fetch(url);
    state.kbEntries = await res.json();
    renderKbList();
  } catch (e) { /* ignore */ }
}

function renderKbList() {
  const el = document.getElementById('kbList');
  if (!state.kbEntries.length) {
    el.innerHTML = '<p class="empty-state">暂无标准条款，点击上方「新增条款」添加</p>';
    return;
  }

  el.innerHTML = `
    <table>
      <thead><tr>
        <th>标题</th>
        <th>分类</th>
        <th>风险等级</th>
        <th>标签</th>
        <th>更新时间</th>
        <th>操作</th>
      </tr></thead>
      <tbody>
        ${state.kbEntries.map(e => `
          <tr>
            <td><strong>${e.title}</strong></td>
            <td><span class="tag tag-mid">${e.category}</span></td>
            <td><span class="tag tag-${riskClass(e.risk_level)}">${e.risk_level}</span></td>
            <td class="text-muted">${e.tags || '-'}</td>
            <td class="text-muted">${e.updated_at}</td>
            <td>
              <button class="btn btn-sm btn-secondary" onclick="editKbEntry(${e.id})">编辑</button>
              <button class="btn btn-sm btn-danger" onclick="deleteKbEntry(${e.id})">删除</button>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function riskClass(r) {
  if (r === '高') return 'high';
  if (r === '低') return 'low';
  return 'mid';
}

function setupKb() {
  document.getElementById('addKbBtn').addEventListener('click', () => openKbModal());
  document.getElementById('kbCancel').addEventListener('click', () => closeKbModal());
  document.querySelector('#kbModal .modal-close').addEventListener('click', () => closeKbModal());
  document.getElementById('kbSave').addEventListener('click', saveKbEntry);

  document.getElementById('kbCategoryFilter').addEventListener('change', e => {
    loadKbEntries(e.target.value, document.getElementById('kbSearch').value);
  });

  let searchTimer;
  document.getElementById('kbSearch').addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      loadKbEntries(document.getElementById('kbCategoryFilter').value, e.target.value);
    }, 300);
  });
}

function openKbModal(entry = null) {
  document.getElementById('kbModalTitle').textContent = entry ? '编辑标准条款' : '新增标准条款';
  document.getElementById('kbEditId').value = entry ? entry.id : '';
  document.getElementById('kbTitle').value = entry ? entry.title : '';
  document.getElementById('kbCategory').value = entry ? entry.category : '通用';
  document.getElementById('kbRiskLevel').value = entry ? entry.risk_level : '中';
  document.getElementById('kbTags').value = entry ? entry.tags : '';
  document.getElementById('kbContent').value = entry ? entry.content : '';
  document.getElementById('kbModal').classList.remove('hidden');
}

function closeKbModal() {
  document.getElementById('kbModal').classList.add('hidden');
}

async function saveKbEntry() {
  const id = document.getElementById('kbEditId').value;
  const data = {
    title: document.getElementById('kbTitle').value.trim(),
    category: document.getElementById('kbCategory').value,
    risk_level: document.getElementById('kbRiskLevel').value,
    tags: document.getElementById('kbTags').value.trim(),
    content: document.getElementById('kbContent').value.trim(),
  };

  if (!data.title || !data.content) {
    alert('标题和内容不能为空');
    return;
  }

  try {
    const url = id ? `${API}/api/kb/entries/${id}` : `${API}/api/kb/entries`;
    const method = id ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });

    if (res.ok) {
      closeKbModal();
      loadKbEntries();
      loadKbCategories();
    } else {
      const err = await res.json();
      alert(`保存失败: ${err.detail || '未知错误'}`);
    }
  } catch (e) {
    alert('网络错误');
  }
}

function editKbEntry(id) {
  const entry = state.kbEntries.find(e => e.id === id);
  if (entry) openKbModal(entry);
}

async function deleteKbEntry(id) {
  if (!confirm('确定删除此标准条款？')) return;
  await fetch(`${API}/api/kb/entries/${id}`, { method: 'DELETE' });
  loadKbEntries();
}

// ── KB Import (vector store) ──

function setupKbImport() {
  const fileInput = document.getElementById('kbFileInput');
  const selectBtn = document.getElementById('kbSelectFileBtn');
  const importFileBtn = document.getElementById('kbImportFileBtn');
  const importUrlBtn = document.getElementById('kbImportUrlBtn');
  if (!selectBtn) return;  // page not loaded yet
  selectBtn.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    const nameEl = document.getElementById('kbFileName');
    nameEl.textContent = fileInput.files[0] ? fileInput.files[0].name : '';
    document.getElementById('kbFileStatus').textContent = '';
  });
  importFileBtn.addEventListener('click', importKbFile);
  importUrlBtn.addEventListener('click', importKbUrl);
  document.querySelector('.tab-btn[data-tab="knowledge"]').addEventListener('click', loadKbSources);
  loadKbSources();
}

async function importKbFile() {
  const fileInput = document.getElementById('kbFileInput');
  const status = document.getElementById('kbFileStatus');
  if (!fileInput.files[0]) { status.textContent = '请先选择文件'; status.className = 'kb-status error'; return; }
  status.textContent = '导入中...'; status.className = 'kb-status';
  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  try {
    const res = await fetch(`${API}/api/kb/import-file`, { method: 'POST', body: formData });
    const data = await res.json();
    if (res.ok) {
      status.textContent = '✅ 导入成功'; status.className = 'kb-status success';
      fileInput.value = ''; document.getElementById('kbFileName').textContent = '';
      loadKbSources();
    } else {
      status.textContent = `❌ ${data.detail || '导入失败'}`; status.className = 'kb-status error';
    }
  } catch (e) {
    status.textContent = '❌ 网络错误'; status.className = 'kb-status error';
  }
}

async function importKbUrl() {
  const urlInput = document.getElementById('kbUrlInput');
  const status = document.getElementById('kbUrlStatus');
  if (!urlInput.value.trim() || !urlInput.value.startsWith('http')) {
    status.textContent = '请输入有效 URL'; status.className = 'kb-status error'; return;
  }
  status.textContent = '导入中...'; status.className = 'kb-status';
  try {
    const formData = new URLSearchParams();
    formData.append('url', urlInput.value.trim());
    const res = await fetch(`${API}/api/kb/import-url`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formData,
    });
    const data = await res.json();
    if (res.ok) {
      status.textContent = '✅ 导入成功'; status.className = 'kb-status success';
      urlInput.value = '';
      loadKbSources();
    } else {
      status.textContent = `❌ ${data.detail || '导入失败'}`; status.className = 'kb-status error';
    }
  } catch (e) {
    status.textContent = '❌ 网络错误'; status.className = 'kb-status error';
  }
}

async function loadKbSources() {
  const el = document.getElementById('kbSourceList');
  try {
    const res = await fetch(`${API}/api/kb/sources`);
    if (!res.ok) return;
    const sources = await res.json();
    if (!sources.length) {
      el.innerHTML = '<p class="empty-state">暂无导入文档</p>';
      return;
    }
    el.innerHTML = sources.map(s => `
      <div class="kb-source-item">
        <div>
          <div class="source-name">${s.source_name}</div>
          <div class="source-meta">${s.source_type === 'url' ? '🌐 URL' : '📄 文件'} · ${s.chunk_count || 0} 个片段</div>
        </div>
        <button class="btn btn-sm btn-danger" onclick="deleteKbSource(${s.id})">删除</button>
      </div>
    `).join('');
  } catch (e) {
    el.innerHTML = '<p class="empty-state">加载失败</p>';
  }
}

async function deleteKbSource(id) {
  if (!confirm('确定删除？关联的向量数据也会删除。')) return;
  await fetch(`${API}/api/kb/sources/${id}`, { method: 'DELETE' });
  loadKbSources();
}

// ═══════════════════════════════════════════
// REVIEW
// ═══════════════════════════════════════════

function loadReviewDocs() {
  const sel = document.getElementById('reviewDocSelect');
  const currentVal = sel.value;
  sel.innerHTML = '<option value="">请选择文档...</option>';
  state.documents.forEach(d => {
    const opt = document.createElement('option');
    opt.value = d.id;
    opt.textContent = `${d.original_name} (${d.clause_count || 0} 条款)`;
    sel.appendChild(opt);
  });
  if (currentVal) sel.value = currentVal;
}

function setupReview() {
  document.getElementById('startReviewBtn').addEventListener('click', startReview);
}

async function startReview() {
  const docId = document.getElementById('reviewDocSelect').value;
  if (!docId) { alert('请先选择文档'); return; }

  const loading = document.getElementById('reviewLoading');
  const result = document.getElementById('reviewResult');
  loading.classList.remove('hidden');
  result.classList.add('hidden');

  try {
    const res = await fetch(`${API}/api/review/${docId}`, { method: 'POST' });
    const data = await res.json();
    loading.classList.add('hidden');

    if (res.ok) {
      state.currentReviewDocId = docId;
      renderReviewResult(data.result);
    } else {
      alert(`审核失败: ${data.detail || '未知错误'}`);
    }
  } catch (e) {
    loading.classList.add('hidden');
    alert('网络错误');
  }
}

function renderReviewResult(result) {
  const el = document.getElementById('reviewResult');
  el.classList.remove('hidden');

  // Summary cards
  const summary = document.getElementById('reviewSummary');
  summary.innerHTML = `
    <div class="summary-card">
      <div class="num">${result.total_clauses}</div>
      <div class="label">总条款数</div>
    </div>
    <div class="summary-card" style="border-color: var(--success);">
      <div class="num" style="color: var(--success);">${result.matched}</div>
      <div class="label">✅ 匹配</div>
    </div>
    <div class="summary-card" style="border-color: var(--danger);">
      <div class="num" style="color: var(--danger);">${result.conflicted}</div>
      <div class="label">⚠️ 冲突</div>
    </div>
    <div class="summary-card" style="border-color: var(--warning);">
      <div class="num" style="color: var(--warning);">${result.missing}</div>
      <div class="label">❓ 缺失</div>
    </div>
    <div class="summary-card" style="border-color: var(--danger);">
      <div class="num" style="color: var(--danger);">${result.high_risk}</div>
      <div class="label">🔴 高风险</div>
    </div>
    <div class="summary-card" style="border-color: var(--warning);">
      <div class="num" style="color: var(--warning);">${result.medium_risk}</div>
      <div class="label">🟡 中风险</div>
    </div>
    <div class="summary-card" style="border-color: var(--success);">
      <div class="num" style="color: var(--success);">${result.low_risk}</div>
      <div class="label">🟢 低风险</div>
    </div>
    <div class="summary-actions">
      <button class="btn btn-primary" onclick="downloadAnnotated()">⬇ 下载 AI 批注版</button>
    </div>
  `;

  // Annotations
  const list = document.getElementById('annotationList');
  if (!result.annotations || !result.annotations.length) {
    list.innerHTML = '<p class="empty-state">所有条款均与知识库标准一致 ✅</p>';
    return;
  }

  list.innerHTML = result.annotations.map(a => `
    <div class="annotation-item ${a.match_type}">
      <div class="flex-row">
        <strong>第 ${a.clause_index} 条</strong>
        <span class="tag tag-${riskClass(a.risk_level)}">${a.risk_level}风险</span>
        <span class="tag tag-${a.match_type}">${matchLabel(a.match_type)}</span>
        <span class="text-muted ml-auto">${a.kb_title || ''}</span>
      </div>
      <div class="clause-text">${truncate(a.clause_content, 200)}</div>
      <div class="comment">${a.comment}</div>
      ${a.suggestion ? `<div class="suggestion">💡 ${a.suggestion}</div>` : ''}
    </div>
  `).join('');
}

function matchLabel(t) {
  const m = { match: '✅ 匹配', conflict: '⚠️ 冲突', missing: '❓ 缺失' };
  return m[t] || t;
}

function truncate(s, max) {
  return s && s.length > max ? s.substring(0, max) + '...' : s;
}

function downloadAnnotated() {
  const docId = state.currentReviewDocId;
  if (!docId) { alert('请先进行审核'); return; }
  // Open download in new tab (avoids auto redirect)
  window.open(`${API}/api/review/${docId}/annotated`, '_blank');
}
