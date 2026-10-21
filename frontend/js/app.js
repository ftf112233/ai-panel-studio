/* AI 圆桌讨论 前端：hash 路由 + SSE 流式渲染 + Transcript 侧栏
   约定：前端不拼 Prompt、不直连 LLM，只消费后端 SSE 事件（见架构文档 §2.4） */

const app = document.getElementById('app');
const API = '';

/* ---------------- utils ---------------- */
const esc = s => (s || '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
async function getJSON(url, opts) {
  const r = await fetch(API + url, opts);
  if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
  return r.json();
}
function avatarHTML(p, size) {
  const st = size ? `width:${size}px;height:${size}px;flex:0 0 ${size}px;` : '';
  return `<div class="avatar" style="background:${p.color || '#868e96'};${st}">${esc(p.avatar || (p.name || '?')[0])}</div>`;
}

/* ---------------- home ---------------- */
async function renderHome() {
  app.innerHTML = `
    <h2 class="page-title">圆桌列表</h2>
    <p class="page-sub">发起一场主题讨论，让立场不同的 AI 嘉宾当场交锋。</p>
    <div class="debate-list" id="list"><div class="empty">加载中…</div></div>`;
  const list = document.getElementById('list');
  try {
    const items = await getJSON('/api/debates');
    if (!items.length) {
      list.innerHTML = `<div class="empty">还没有圆桌，<a href="#/create">发起第一场 →</a></div>`;
      return;
    }
    list.innerHTML = items.map(d => `
      <div class="debate-item" data-id="${d.id}">
        <div>
          <h3>${esc(d.topic)}</h3>
          <div class="debate-meta">${new Date(d.created_at).toLocaleString()} · ${d.message_count} 条发言 · ${d.persona_ids.length} 位嘉宾</div>
        </div>
        <span class="badge ${d.status}">${{ created: '待开始', running: '进行中', done: '已结束', failed: '异常' }[d.status]}</span>
      </div>`).join('');
    list.querySelectorAll('.debate-item').forEach(el =>
      el.onclick = () => location.hash = `#/live/${el.dataset.id}`);
  } catch (e) {
    list.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  }
}

/* ---------------- create ---------------- */
async function renderCreate() {
  app.innerHTML = `
    <h2 class="page-title">发起圆桌</h2>
    <p class="page-sub">选择 2-5 位立场不同的嘉宾，分歧越真实，讨论越有价值。</p>
    <div class="card">
      <div class="field">
        <label>讨论主题</label>
        <input type="text" id="topic" placeholder="例：AI 编程工具会取代初级程序员吗？" />
      </div>
      <div class="field">
        <label>选择嘉宾（<span id="cnt">0</span>/5）</label>
        <div class="persona-grid" id="grid">加载中…</div>
      </div>
      <button class="btn" id="start">开始圆桌</button>
      <span id="err" style="color:#e03131;font-size:13px;margin-left:10px"></span>
    </div>`;

  const grid = document.getElementById('grid');
  const picked = new Set();
  const personas = await getJSON('/api/personas');
  grid.innerHTML = personas.map(p => `
    <div class="persona" data-id="${p.id}">
      ${avatarHTML(p)}
      <div>
        <div class="pname">${esc(p.name)}<small style="color:${p.color}"> · ${esc(p.title)}</small></div>
        <div class="pstance">${esc(p.stance)}</div>
      </div>
    </div>`).join('');
  grid.querySelectorAll('.persona').forEach(el => el.onclick = () => {
    const id = el.dataset.id;
    picked.has(id) ? picked.delete(id) : picked.add(id);
    el.classList.toggle('on', picked.has(id));
    document.getElementById('cnt').textContent = picked.size;
  });

  document.getElementById('start').onclick = async () => {
    const topic = document.getElementById('topic').value.trim();
    const err = document.getElementById('err');
    if (topic.length < 2) return err.textContent = '主题至少 2 个字';
    if (picked.size < 2) return err.textContent = '至少选 2 位嘉宾';
    err.textContent = '';
    try {
      const d = await getJSON('/api/debates', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, persona_ids: [...picked] })
      });
      location.hash = `#/live/${d.id}`;
    } catch (e) { err.textContent = e.message; }
  };
}

/* ---------------- archive ---------------- */
async function renderArchive() {
  app.innerHTML = `
    <h2 class="page-title">历史归档</h2>
    <p class="page-sub">已结束的圆桌，可查看完整 Transcript 与主持人总结。</p>
    <div class="debate-list" id="list"><div class="empty">加载中…</div></div>`;
  const list = document.getElementById('list');
  const items = (await getJSON('/api/debates')).filter(d => d.status === 'done' || d.status === 'failed');
  if (!items.length) return list.innerHTML = `<div class="empty">暂无归档</div>`;
  list.innerHTML = items.map(d => `
    <div class="debate-item" data-id="${d.id}">
      <div>
        <h3>${esc(d.topic)}</h3>
        <div class="debate-meta">${new Date(d.created_at).toLocaleString()} · ${d.message_count} 条发言</div>
        ${d.summary ? `<div class="debate-meta" style="margin-top:6px">总结：${esc(d.summary.slice(0, 80))}…</div>` : ''}
      </div>
      <span class="badge ${d.status}">${d.status === 'done' ? '已结束' : '异常'}</span>
    </div>`).join('');
  list.querySelectorAll('.debate-item').forEach(el =>
    el.onclick = () => location.hash = `#/live/${el.dataset.id}`);
}

/* ---------------- live ---------------- */
function renderLive(debateId) {
  const tpl = document.getElementById('tpl-live').content.cloneNode(true);
  app.innerHTML = '';
  app.appendChild(tpl);

  const els = {
    topic: app.querySelector('.topic'),
    round: app.querySelector('.badge.round'),
    focus: app.querySelector('.focus'),
    messages: document.getElementById('messages'),
    status: document.getElementById('live-status'),
    tr: document.getElementById('transcript'),
    trBody: document.getElementById('tr-body'),
  };
  document.getElementById('btn-transcript').onclick = () => els.tr.classList.add('open');
  document.getElementById('btn-close-tr').onclick = () => els.tr.classList.remove('open');

  const people = {};   // id -> {name,color,avatar}
  const transcript = [];
  let current = null;  // 当前正在流式的消息 DOM
  let thinking = null;

  function addThinking(name) {
    removeThinking();
    thinking = document.createElement('div');
    thinking.className = 'thinking';
    thinking.innerHTML = `<div class="dots"><span></span><span></span><span></span></div>${esc(name)} 正在思考…`;
    els.messages.appendChild(thinking);
    els.status.textContent = `${name} 正在思考…`;
  }
  function removeThinking() { if (thinking) { thinking.remove(); thinking = null; } }

  function startMsg(id, name, degraded) {
    removeThinking();
    const p = people[id] || { name, color: '#868e96', avatar: (name || '?')[0] };
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + (id === 'host' ? 'host' : 'guest');
    wrap.innerHTML = `${avatarHTML(p)}
      <div class="bubble">
        <div class="who">${esc(name)}${id === 'host' ? '<small>主持人</small>' : ''}${degraded ? '<span class="shift-tag">结构降级</span>' : ''}</div>
        <div class="say"><span class="txt"></span><span class="caret"></span></div>
      </div>`;
    els.messages.appendChild(wrap);
    current = { id, name, txt: wrap.querySelector('.txt'), caret: wrap.querySelector('.caret'), text: '' };
    els.status.textContent = `${name} 发言中…`;
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function endMsg(id) {
    if (!current) return;
    if (current.caret) current.caret.remove();
    transcript.push({ id, name: current.name, text: current.text });
    els.trBody.innerHTML = transcript.map(t =>
      `<div class="tr-item ${t.id === 'host' ? 'host' : ''}">
         <div class="t-who">${esc(t.name)}</div><div class="t-say">${esc(t.text)}</div>
       </div>`).join('');
    els.tr.scrollTop = els.tr.scrollHeight;
    current = null;
  }

  function onEvent(ev) {
    const d = ev.data || {};
    switch (ev.event) {
      case 'participants':
        els.topic.textContent = d.topic;
        people[d.host.id] = d.host;
        (d.guests || []).forEach(g => people[g.id] = g);
        els.status.textContent = '已连接';
        break;
      case 'round_change':
        app.querySelector('.badge.round').textContent = `第 ${d.round} 轮`;
        if (d.focus) els.focus.textContent = '聚焦：' + d.focus;
        const sep = document.createElement('div');
        sep.className = 'round-sep';
        sep.innerHTML = `<hr /><span>第 ${d.round} 轮</span>`;
        els.messages.appendChild(sep);
        break;
      case 'focus':
        els.focus.textContent = '聚焦：' + d.focus;
        break;
      case 'thinking':
        addThinking(d.name);
        break;
      case 'speaker_start':
        startMsg(d.speaker, d.name, d.degraded);
        break;
      case 'delta':
        if (current && current.id === d.speaker) {
          current.text += d.text;
          current.txt.textContent = current.text;
          els.messages.scrollTop = els.messages.scrollHeight;
        }
        break;
      case 'speaker_end':
        endMsg(d.speaker);
        break;
      case 'stance':
        if (d.shift !== 'hold') {
          const last = els.messages.querySelector('.msg:last-child .who');
          if (last) last.insertAdjacentHTML('beforeend',
            `<span class="shift-tag ${d.shift}">${d.shift === 'change' ? '立场改变' : '立场松动'}</span>`);
        }
        break;
      case 'error':
        els.status.textContent = `⚠️ ${d.message}` + (d.recoverable ? '（可刷新重试）' : '');
        break;
      case 'done':
        removeThinking();
        els.status.textContent = d.replay ? '回放结束（历史记录）' : '圆桌结束';
        if (d.summary) {
          const s = document.createElement('div');
          s.className = 'card';
          s.style.marginTop = '16px';
          s.innerHTML = `<h3 style="margin:0 0 8px;font-size:15px">主持人总结</h3><div>${esc(d.summary)}</div>`;
          els.messages.appendChild(s);
        }
        es.close();
        break;
    }
  }

  const es = new EventSource(`${API}/api/debates/${debateId}/stream`);
  es.onmessage = e => { try { onEvent(JSON.parse(e.data)); } catch (_) {} };
  es.onerror = () => { els.status.textContent = '连接中断，正在重连…'; };
}

/* ---------------- router ---------------- */
function route() {
  const h = location.hash.replace(/^#/, '') || '/';
  document.querySelectorAll('.nav a').forEach(a =>
    a.classList.toggle('active', a.getAttribute('href') === '#' + h.split('/')[1] ? true : false));
  if (h === '/' ) return renderHome();
  if (h === '/create') return renderCreate();
  if (h === '/archive') return renderArchive();
  const m = h.match(/^\/live\/(.+)$/);
  if (m) return renderLive(m[1]);
  renderHome();
}
window.addEventListener('hashchange', route);

(async function init() {
  try {
    const h = await getJSON('/api/health');
    document.getElementById('mode').textContent = h.mode === 'mock' ? 'Mock 流式（未配置 Key）' : `${h.model}`;
  } catch (_) {}
  route();
})();
