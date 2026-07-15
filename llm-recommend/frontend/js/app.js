const API = '';
let currentUserId = 0;

// 快捷标签
const QUICK_QUERIES = [
    '送女朋友的礼物', '性价比高的耳机', '适合跑步的装备',
    '提升办公效率', '学生党推荐', '科技数码发烧友',
    '护肤美妆好物', '户外探险装备', '程序员必读',
];

async function init() {
    // 加载用户列表
    const users = await fetch(`${API}/api/users`).then(r => r.json());
    const sel = document.getElementById('userSelect');
    users.forEach(u => {
        const opt = document.createElement('option');
        opt.value = u.id; opt.textContent = u.display_name;
        sel.appendChild(opt);
    });
    sel.onchange = () => { currentUserId = +sel.value; doSearch(); };

    // 快捷标签
    const tagBox = document.getElementById('quickTags');
    QUICK_QUERIES.forEach(q => {
        const btn = document.createElement('button');
        btn.textContent = q;
        btn.onclick = () => { document.getElementById('queryInput').value = q; doSearch(); };
        tagBox.appendChild(btn);
    });

    // 回车搜索
    document.getElementById('queryInput').onkeydown = e => { if (e.key === 'Enter') doSearch(); };

    // 初始推荐
    doSearch();
}

async function doSearch() {
    const query = document.getElementById('queryInput').value.trim();
    const area = document.getElementById('resultArea');
    area.innerHTML = '<div class="loading">🔄 推荐中...</div>';

    try {
        const data = await fetch(`${API}/api/recommend/${currentUserId}?q=${encodeURIComponent(query)}&top_k=12`).then(r => r.json());
        renderResults(data, query);
    } catch (e) {
        area.innerHTML = `<div class="explanation">❌ 请求失败: ${e.message}</div>`;
    }
}

function renderResults(data, query) {
    const area = document.getElementById('resultArea');
    let html = '';

    // 策略标签
    html += `<div class="strategy-badge">📍 ${data.strategy}</div>`;

    // 推荐解释
    html += `<div class="explanation">${data.explanation}</div>`;

    // 结果头
    html += `<div class="results-header"><h2>${query ? '搜索结果' : '为你推荐'}</h2><span>${data.count} 件商品</span></div>`;

    // 商品卡片
    html += '<div class="grid">';
    data.items.forEach(item => {
        const tags = (item.tags || '').split(',').slice(0, 3).map(t => `<span class="card-tag">${t}</span>`).join('');
        html += `
        <div class="card" onclick="interact(${item.id}, 'view')">
            <div class="card-top">
                <span class="card-name">${item.name}</span>
                <span class="card-price">${item.price}</span>
            </div>
            <div class="card-meta"><span class="card-tag">${item.category}</span>${tags}</div>
            <div class="card-desc">${item.description || ''}</div>
            <div class="card-actions">
                <button onclick="event.stopPropagation();interact(${item.id},'like',this)">👍 喜欢</button>
                <button onclick="event.stopPropagation();interact(${item.id},'cart')">🛒 加购</button>
                <button onclick="event.stopPropagation();interact(${item.id},'purchase')">💳 购买</button>
            </div>
        </div>`;
    });
    html += '</div>';

    area.innerHTML = html;
}

async function interact(itemId, action, btn) {
    if (!currentUserId) { alert('请先选择用户'); return; }
    await fetch(`${API}/api/interact?user_id=${currentUserId}&item_id=${itemId}&action=${action}`, { method: 'POST' });
    if (btn && action === 'like') { btn.classList.add('liked'); btn.textContent = '❤️ 已喜欢'; }
}

async function showProfile() {
    if (!currentUserId) { alert('请先选择用户'); return; }
    const section = document.getElementById('profileSection');
    section.classList.toggle('show');
    if (!section.classList.contains('show')) return;

    const summary = document.getElementById('profileSummary');
    summary.textContent = '加载中...';
    try {
        const data = await fetch(`${API}/api/profile/${currentUserId}`).then(r => r.json());
        summary.innerHTML = `<strong>${data.user?.display_name}</strong>：${data.summary || '暂无分析'}`;
    } catch (e) {
        summary.textContent = '加载失败';
    }
}

init();
