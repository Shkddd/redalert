/* ChatBI — Frontend Application */

const API_BASE = '/api';
let conversationId = crypto.randomUUID?.() || Math.random().toString(36).slice(2);
let chartInstance = null;

// DOM refs
const $ = (s) => document.querySelector(s);
const messagesEl = $('#messages');
const welcomeEl = $('#welcome');
const input = $('#query-input');
const sendBtn = $('#send-btn');
const suggestions = $('#suggestions');
const sqlDisplay = $('#sql-display');
const sqlText = $('#sql-text');
const resultsPanel = $('#results-panel');
const panelOverlay = $('#panel-overlay');
const panelBackdrop = $('#panel-backdrop');
const chartContainer = $('#chart-container');
const chartCanvas = $('#chart-canvas');
const tableContainer = $('#table-container');
const tableHead = $('#table-head');
const tableBody = $('#table-body');
const resultMeta = $('#result-meta');
const statusDot = $('#status-dot');
const statusText = $('#status-text');
const fileInput = $('#file-input');
const uploadBtn = $('#upload-btn');
const uploadList = $('#upload-list');

// ====== Init ======
async function init() {
    await checkHealth();
    await loadSuggestions();
    await loadUploads();
    setupEvents();
    autoResize(input);
}

// ====== Health check ======
async function checkHealth() {
    try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 5000);
        const res = await fetch(`${API_BASE}/health`, { signal: controller.signal });
        clearTimeout(timeout);
        const data = await res.json();
        statusDot.className = 'dot online';
        statusText.textContent = data.llm_configured ? '已连接 (已配置LLM)' : '已连接 (未配置LLM)';
        if (!data.seed_data_loaded) {
            statusText.textContent += ' - 无数据';
        }
    } catch {
        statusDot.className = 'dot offline';
        statusText.textContent = '无法连接后端';
    }
}

// ====== Load suggestion questions ======
async function loadSuggestions() {
    try {
        const res = await fetch(`${API_BASE}/metrics`);
        const items = await res.json();
        suggestions.innerHTML = items.map(q =>
            `<button class="suggestion-btn" data-q="${q.question}">${q.question}</button>`
        ).join('');
    } catch {
        suggestions.innerHTML = '<p style="font-size:12px;color:#767a8a;">无法加载建议</p>';
    }
}

// ====== Events ======
function setupEvents() {
    // Send on Enter (Shift+Enter for newline)
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    });
    input.addEventListener('input', () => {
        sendBtn.disabled = !input.value.trim();
        autoResize(input);
    });
    sendBtn.addEventListener('click', send);

    // Suggestion clicks
    suggestions.addEventListener('click', (e) => {
        const btn = e.target.closest('.suggestion-btn');
        if (btn) {
            input.value = btn.dataset.q;
            sendBtn.disabled = false;
            autoResize(input);
            send();
        }
    });

    // Copy SQL
    $('#copy-sql').addEventListener('click', () => {
        navigator.clipboard.writeText(sqlText.textContent).catch(() => {});
    });

    // Close results panel (X button + backdrop click)
    $('#close-panel').addEventListener('click', closePanel);
    panelBackdrop.addEventListener('click', closePanel);

    // New chat
    $('#new-chat-btn').addEventListener('click', newChat);

    // Auto-focus
    document.addEventListener('click', () => input.focus());

    // Upload button triggers hidden file input
    uploadBtn.addEventListener('click', () => fileInput.click());

    // File selected -> upload
    fileInput.addEventListener('change', async () => {
        const file = fileInput.files[0];
        if (!file) return;
        if (!file.name.endsWith('.xlsx')) {
            addMessage('只支持 .xlsx 格式的Excel文件', 'bot');
            fileInput.value = '';
            return;
        }
        await uploadFile(file);
        fileInput.value = '';
    });
}

// ====== Send message ======
async function send() {
    const text = input.value.trim();
    if (!text) return;

    // Clear welcome, add user message
    welcomeEl.style.display = 'none';
    addMessage(text, 'user');
    input.value = '';
    sendBtn.disabled = true;
    sqlDisplay.classList.add('hidden');
    resultsPanel.classList.add('hidden');
    panelOverlay.classList.add('hidden');

    // Show typing
    const typingId = 'typing-' + Date.now();
    const typingEl = document.createElement('div');
    typingEl.className = 'message bot';
    typingEl.id = typingId;
    typingEl.innerHTML = '<div class="avatar">🤖</div><div class="bubble"><div class="typing-indicator"><span></span><span></span><span></span></div></div>';
    messagesEl.appendChild(typingEl);
    scrollToBottom();

    const controller = new AbortController();
    const chatTimeout = setTimeout(() => controller.abort(), 60000);
    try {
        const res = await fetch(`${API_BASE}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                conversation_id: conversationId,
            }),
            signal: controller.signal,
        });
        clearTimeout(chatTimeout);
        const data = await res.json();
        typingEl.remove();

        // Show SQL
        if (data.sql && data.sql.trim()) {
            sqlText.textContent = data.sql;
            sqlDisplay.classList.remove('hidden');
        }

        // Show bot response
        addMessage(data.answer || '(无响应)', 'bot');

        // Show results panel
        if (data.data && data.data.length > 0) {
            renderResults(data);
            panelOverlay.classList.remove('hidden');
        } else if (data.error) {
            panelOverlay.classList.remove('hidden');
            renderError(data);
        }
    } catch (err) {
        clearTimeout(chatTimeout);
        typingEl.remove();
        addMessage(`请求失败: ${err.message}`, 'bot');
    }
}

// ====== Add message bubble ======
function addMessage(content, role) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    const avatar = role === 'user' ? '🧑‍💻' : '🤖';
    div.innerHTML = `<div class="avatar">${avatar}</div><div class="bubble">${escapeHtml(content)}</div>`;
    messagesEl.appendChild(div);
    scrollToBottom();
}

// ====== Render results ======
function renderResults(data) {
    const { columns, data: rows, chart_type, chart_data, execution_time_ms, sql } = data;

    // Table
    if (rows && rows.length > 0 && columns) {
        tableContainer.classList.remove('hidden');
        tableHead.innerHTML = `<tr>${columns.map(c => `<th>${c}</th>`).join('')}</tr>`;
        tableBody.innerHTML = rows.slice(0, 50).map(row =>
            `<tr>${columns.map(c => `<td>${escapeHtml(String(row[c] ?? ''))}</td>`).join('')}</tr>`
        ).join('');
    } else {
        tableContainer.classList.add('hidden');
    }

    // Chart
    if (chart_data && chart_data.labels && chart_data.labels.length > 0) {
        chartContainer.classList.remove('hidden');
        renderChart(chart_data);
    } else {
        chartContainer.classList.add('hidden');
    }

    // Meta
    resultMeta.textContent = `查询完成 · ${rows.length} 条结果 · ${execution_time_ms || 0}ms`;
}

function renderError(data) {
    tableContainer.classList.add('hidden');
    chartContainer.classList.add('hidden');
    resultMeta.textContent = `错误: ${data.error || '未知错误'}`;
}

// ====== Chart rendering ======
function renderChart(chartData) {
    if (chartInstance) chartInstance.destroy();

    const ctx = chartCanvas.getContext('2d');
    const colors = [
        '#4f6ef7', '#34d399', '#f59e0b', '#ef4444',
        '#8b5cf6', '#06b6d4', '#ec4899', '#14b8a6',
    ];

    const datasets = chartData.datasets.map((ds, i) => ({
        label: ds.label,
        data: ds.data,
        backgroundColor: chartData.type === 'pie'
            ? colors.slice(0, ds.data.length)
            : colors[i % colors.length] + '80',
        borderColor: colors[i % colors.length],
        borderWidth: 2,
        tension: 0.3,
        fill: chartData.type === 'line' ? false : undefined,
    }));

    chartInstance = new Chart(ctx, {
        type: chartData.type === 'bar' ? 'bar' : chartData.type,
        data: {
            labels: chartData.labels,
            datasets: datasets,
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: datasets.length > 1, position: 'bottom' },
            },
            scales: chartData.type !== 'pie' ? {
                y: {
                    beginAtZero: true,
                    ticks: { callback: v => v >= 10000 ? (v/10000).toFixed(1)+'w' : v },
                }
            } : undefined,
        },
    });
}

// ====== Close results panel ======
function closePanel() {
    panelOverlay.classList.add('hidden');
}

// ====== New conversation ======
function newChat() {
    // Clear server-side history
    fetch(`${API_BASE}/history/${conversationId}`, { method: 'DELETE' }).catch(() => {});
    conversationId = crypto.randomUUID?.() || Math.random().toString(36).slice(2);
    messagesEl.innerHTML = '';
    welcomeEl.style.display = '';
    sqlDisplay.classList.add('hidden');
    resultsPanel.classList.add('hidden');
    panelOverlay.classList.add('hidden');
    if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
    input.focus();
}

// ====== Upload Excel ======
async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    const typingId = 'upload-typing-' + Date.now();
    const typingEl = document.createElement('div');
    typingEl.className = 'message bot';
    typingEl.id = typingId;
    typingEl.innerHTML = '<div class="avatar">🤖</div><div class="bubble">正在导入 <strong>' + escapeHtml(file.name) + '</strong> ...</div>';
    welcomeEl.style.display = 'none';
    messagesEl.appendChild(typingEl);
    scrollToBottom();

    try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 120000);
        const res = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData,
            signal: controller.signal,
        });
        clearTimeout(timeout);
        typingEl.remove();

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '请求失败' }));
            addMessage('导入失败: ' + (err.detail || '未知错误'), 'bot');
            return;
        }

        const data = await res.json();
        addMessage(
            '成功导入 ' + escapeHtml(data.original_filename) + '\n' +
            '表名: ' + data.table_name + '\n' +
            data.row_count + ' 行 x ' + data.column_count + ' 列',
            'bot'
        );
        await loadUploads();
    } catch (err) {
        typingEl.remove();
        addMessage('上传失败: ' + err.message, 'bot');
    }
}

async function loadUploads() {
    try {
        const res = await fetch(`${API_BASE}/uploads`);
        if (!res.ok) {
            uploadList.innerHTML = '<p class="upload-empty">无法加载上传列表</p>';
            return;
        }
        const data = await res.json();
        if (!data.uploads || data.uploads.length === 0) {
            uploadList.innerHTML = '<p class="upload-empty">暂无上传数据</p>';
            return;
        }
        uploadList.innerHTML = data.uploads.map(u =>
            '<div class="upload-item" data-table="' + escapeHtml(u.table_name) + '">' +
                '<div class="upload-info">' +
                    '<span class="upload-name" title="' + escapeHtml(u.table_name) + '">' + escapeHtml(u.display_name) + '</span>' +
                    '<span class="upload-meta">' + u.row_count + '行 x ' + u.column_count + '列</span>' +
                '</div>' +
                '<button class="upload-delete-btn" title="删除此表">x</button>' +
            '</div>'
        ).join('');

        document.querySelectorAll('.upload-delete-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const item = btn.closest('.upload-item');
                const tableName = item.dataset.table;
                if (confirm('确定要删除表 "' + tableName + '" 吗？此操作不可撤销。')) {
                    await deleteUpload(tableName);
                }
            });
        });
    } catch {
        uploadList.innerHTML = '<p class="upload-empty">无法加载上传列表</p>';
    }
}

async function deleteUpload(tableName) {
    try {
        const res = await fetch(`${API_BASE}/uploads/${encodeURIComponent(tableName)}`, {
            method: 'DELETE',
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '删除失败' }));
            addMessage('删除失败: ' + (err.detail || '未知错误'), 'bot');
            return;
        }
        addMessage('已删除表: ' + tableName, 'bot');
        await loadUploads();
    } catch (err) {
        addMessage('删除失败: ' + err.message, 'bot');
    }
}

// ====== Utilities ======
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}
function scrollToBottom() {
    document.querySelector('#chat-container').scrollTop = 1e9;
}

// ====== Go! ======
document.addEventListener('DOMContentLoaded', init);
