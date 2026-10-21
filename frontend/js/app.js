/* AI Panel Studio 前端：hash 路由 + SSE 流式渲染
   约定：前端不拼 Prompt、不直连 LLM、不接触 API Key，只消费后端 SSE 事件 */

const app = document.getElementById('app');
const API = '';

const esc = s => (s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
async function getJSON(url, opts) {
  const r = await fetch(API + url, opts);
  if (!r.ok) throw new Error(((await r.json()).detail) || r.statusText);
  return r.json();
}
const STATUS_TEXT = { created: '待开始', running: '进行中', done: '已结束', failed: '异常' };
const ACTION_TEXT = { raise_hand: '举手', supplement: '补充', rebut: '反驳' };

function avatarsHTML(experts) {
  return `<div class="avatars">${experts.map(e =>
    `<i style="background:${e.color}" title="${esc(e.name)}">${esc((e.name || '?')[0])}</i>`).join('')}</div>`;
}

function setPageScroll(on) {
  document.querySelector('main').classList.toggle('scroll-page', !!on);
}

/* ---------------- 首页：讨论列表 ---------------- */
async function renderHome() {
  setPageScroll(true);
  app.innerHTML = `
    <div class="page-wrap">
      <h2 class="page-title">讨论列表</h2>
      <p class="page-sub">加入观察一场正在进行的讨论，或发起一场新的圆桌。</p>
      <div class="debate-list" id="list"><div class="empty">加载中…</div></div>
    </div>`;
  const list = document.getElementById('list');
  try {
    const items = await getJSON('/api/debates');
    if (!items.length) {
      list.innerHTML = `<div class="empty">还没有讨论，<a href="#/create">发起第一场 →</a></div>`;
      return;
    }
    list.innerHTML = items.map(d => `
      <div class="debate-item" data-id="${d.id}">
        <div>
          <h3>${esc(d.topic)}</h3>
          <div class="debate-meta">${new Date(d.created_at).toLocaleString()} · ${d.message_count || 0} 条发言 · ${d.expert_count || 0} 位专家</div>
        </div>
        <div class="row">
          ${avatarsHTML(d.experts || [])}
          <span class="badge ${d.status}">${STATUS_TEXT[d.status] || d.status}</span>
        </div>
      </div>`).join('');
    list.querySelectorAll('.debate-item').forEach(el =>
      el.onclick = () => location.hash = `#/live/${el.dataset.id}`);
  } catch (e) {
    list.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  }
}

/* ---------------- 发起：话题 + 人数 → 生成阵容 → 确认 ---------------- */
async function renderCreate() {
  setPageScroll(true);
  app.innerHTML = `
    <div class="page-wrap">
      <h2 class="page-title">发起讨论</h2>
      <p class="page-sub">输入话题与专家人数，系统会动态生成主持人 + 专家阵容，确认后进入演播厅。</p>
      <div class="card">
        <div class="field">
          <label>讨论话题</label>
          <input type="text" id="topic" placeholder="例：AI 编程工具会取代初级程序员吗？" />
          <div class="row" style="margin-top:10px" id="samples"></div>
        </div>
        <div class="field">
          <label>专家人数（默认 4 人，2-5 人）</label>
          <select id="count">
            <option value="2">2 人</option><option value="3">3 人</option>
            <option value="4" selected>4 人</option><option value="5">5 人</option>
          </select>
        </div>
        <div class="row">
          <button class="btn" id="gen">生成阵容</button>
          <button class="btn" id="enter" style="display:none">确认阵容，进入演播厅</button>
          <span id="err" style="color:#e03131;font-size:13px"></span>
        </div>
      </div>
      <div id="lineup" style="margin-top:16px"></div>
    </div>`;

  // 样例话题（≥5 条，来自后端种子数据）
  try {
    const topics = await getJSON('/api/topics');
    document.getElementById('samples').innerHTML =
      `<span style="color:#6b7280;font-size:13px">样例话题：</span>` + topics.map(t =>
        `<span class="chip" data-topic="${esc(t.topic)}" data-id="${t.id}">${esc(t.topic.slice(0, 16))}…</span>`).join('');
    document.querySelectorAll('#samples .chip').forEach(el => el.onclick = () => {
      document.getElementById('topic').value = el.dataset.topic;
    });
  } catch (_) {}

  let lineup = null;
  const box = document.getElementById('lineup');
  const err = document.getElementById('err');

  document.getElementById('gen').onclick = async () => {
    const topic = document.getElementById('topic').value.trim();
    const count = parseInt(document.getElementById('count').value, 10);
    if (topic.length < 2) return err.textContent = '话题至少 2 个字';
    err.textContent = '生成中…';
    try {
      const res = await getJSON('/api/lineups', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, expert_count: count })
      });
      lineup = res.lineup;
      err.textContent = '';
      box.innerHTML = `
        <h3 style="font-size:15px;margin:0 0 10px">阵容确认</h3>
        <div class="lineup-grid">
          ${cardHTML({ name: lineup.host.name, title: lineup.host.title, occupation: '主持人', stance: '控场、追问、串联与总结', color: '#495057' }, true)}
          ${lineup.experts.map(e => cardHTML(e, false)).join('')}
        </div>`;
      document.getElementById('enter').style.display = '';
    } catch (e) { err.textContent = e.message; }
  };

  document.getElementById('enter').onclick = async () => {
    if (!lineup) return;
    try {
      const d = await getJSON('/api/debates', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: document.getElementById('topic').value.trim(), lineup })
      });
      location.hash = `#/live/${d.id}`;
    } catch (e) { err.textContent = e.message; }
  };

  function cardHTML(p, isHost) {
    return `<div class="lineup-card ${isHost ? 'host' : ''}" style="border-left-color:${p.color}">
      <div class="lc-name"><span class="color-dot" style="background:${p.color}"></span>${esc(p.name)}</div>
      <div class="lc-meta">${esc(p.occupation || '')}${p.title ? ' · ' + esc(p.title) : ''}</div>
      <div class="lc-stance">${esc(p.stance || '')}</div>
    </div>`;
  }
}

/* ---------------- 历史归档 ---------------- */
async function renderArchive() {
  setPageScroll(true);
  app.innerHTML = `
    <div class="page-wrap">
      <h2 class="page-title">历史归档</h2>
      <p class="page-sub">已结束的讨论可查看完整 Transcript、主持人总结与共识/分歧。</p>
      <div class="debate-list" id="list"><div class="empty">加载中…</div></div>
    </div>`;
  const list = document.getElementById('list');
  const items = (await getJSON('/api/debates')).filter(d => d.status === 'done' || d.status === 'failed');
  if (!items.length) return list.innerHTML = `<div class="empty">暂无归档</div>`;
  list.innerHTML = items.map(d => `
    <div class="debate-item" data-id="${d.id}">
      <div>
        <h3>${esc(d.topic)}</h3>
        <div class="debate-meta">${new Date(d.created_at).toLocaleString()} · ${d.message_count || 0} 条发言</div>
        ${d.summary ? `<div class="debate-meta" style="margin-top:6px">总结：${esc(d.summary.slice(0, 90))}…</div>` : ''}
      </div>
      <span class="badge ${d.status}">${STATUS_TEXT[d.status]}</span>
    </div>`).join('');
  list.querySelectorAll('.debate-item').forEach(el =>
    el.onclick = () => location.hash = `#/live/${el.dataset.id}`);
}

/* ---------------- 演播厅 ---------------- */
function renderStudio(debateId) {
  setPageScroll(false);
  app.innerHTML = '';
  app.appendChild(document.getElementById('tpl-studio').content.cloneNode(true));

  const els = {
    topic: app.querySelector('.topic'),
    round: app.querySelector('.badge.round'),
    focus: app.querySelector('.focus'),
    messages: document.getElementById('messages'),
    status: document.getElementById('live-status'),
    foot: document.getElementById('foot-info'),
    agents: document.getElementById('agents'),
    insights: document.getElementById('insights'),
    transcript: document.getElementById('transcript'),
  };
  document.getElementById('btn-tr-clear').onclick = () => els.transcript.innerHTML = '';

  const people = {};        // id -> {name,color,avatar,occupation,title}
  const states = {};        // id -> {status, thought}
  let current = null;
  let transcript = [];

  function renderAgents() {
    els.agents.innerHTML = Object.keys(people).filter(id => id !== 'host').map(id => {
      const p = people[id], st = states[id] || { status: 'standby', thought: '待机中' };
      const label = { standby: '待机', preparing: '准备发言', speaking: '发言中' }[st.status] || '待机';
      return `<div class="agent-win ${st.status}">
        <div class="aw-avatar" style="background:${p.color}">${esc(p.avatar || p.name[0])}</div>
        <div>
          <div class="aw-name">${esc(p.name)}<span class="aw-state">· ${label}</span></div>
          <div class="aw-thought">${esc(st.thought || '')}</div>
        </div>
      </div>`;
    }).join('');
  }

  function renderInsights(consensus, disagreements) {
    els.insights.innerHTML =
      `<div class="ins-block"><div class="ins-title">共识</div>` +
      (consensus.length ? consensus.map(c => `<div class="ins-item consensus">${esc(c)}</div>`).join('')
        : `<div class="debate-meta">暂无</div>`) + `</div>` +
      `<div class="ins-block"><div class="ins-title">分歧</div>` +
      (disagreements.length ? disagreements.map(d =>
        `<div class="ins-item disagreement">${esc(d.a)} ↔ ${esc(d.b)}：${esc(d.point)}</div>`).join('')
        : `<div class="debate-meta">暂无</div>`) + `</div>`;
  }

  function pushTranscript(entry) {
    transcript.push(entry);
    els.transcript.innerHTML = transcript.map(t =>
      `<div class="tr-item ${t.id === 'host' ? 'host' : ''}">
        <div class="t-who"><span class="color-dot" style="background:${t.color}"></span>${esc(t.name)}
          <span class="t-title">${esc(t.title || '')}</span></div>
        <div class="t-say">${esc(t.text)}</div>
      </div>`).join('');
    els.transcript.scrollTop = els.transcript.scrollHeight;
  }

  function startMsg(d) {
    const p = people[d.speaker] || { name: d.name, color: '#868e96', avatar: (d.name || '?')[0], title: '' };
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + (d.speaker === 'host' ? 'host' : 'guest');
    const tagAction = d.action_label ? `<span class="tag ${d.action}">${esc(d.action_label)}</span>` : '';
    const tagInterrupt = d.interrupt ? `<span class="tag interrupt">主持人插话</span>` : '';
    wrap.innerHTML = `
      <div class="aw-avatar" style="background:${p.color}">${esc(p.avatar || p.name[0])}</div>
      <div>
        <div class="who">${esc(d.name)}<small>${esc(p.title || '')}</small>${tagAction}${tagInterrupt}</div>
        <div class="say"><span class="txt"></span><span class="caret"></span></div>
      </div>`;
    els.messages.appendChild(wrap);
    current = { id: d.speaker, name: d.name, color: p.color, title: p.title || '',
                txt: wrap.querySelector('.txt'), caret: wrap.querySelector('.caret'), text: '' };
    els.status.textContent = `${d.name} 发言中…`;
  }

  function endMsg() {
    if (!current) return;
    if (current.caret) current.caret.remove();
    pushTranscript({ id: current.id, name: current.name, color: current.color,
                     title: current.title, text: current.text });
    current = null;
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function onEvent(ev) {
    const d = ev.data || {};
    switch (ev.event) {
      case 'participants':
        els.topic.textContent = d.topic;
        people[d.host.id] = d.host;
        (d.guests || []).forEach(g => { people[g.id] = g; states[g.id] = { status: 'standby', thought: '待机中' }; });
        renderAgents(); renderInsights([], []);
        els.status.textContent = '已连接';
        els.foot.textContent = `${(d.guests || []).length} 位专家 · 主持人 ${d.host.name}`;
        break;
      case 'agent_status':
        if (d.speaker_id && d.speaker_id !== 'host' && people[d.speaker_id]) {
          states[d.speaker_id] = { status: d.status, thought: d.thought };
          renderAgents();
        } else if (d.speaker_id === 'host') {
          els.foot.textContent = `主持人：${esc(d.thought || '')}`;
        }
        break;
      case 'round_change':
        els.round.textContent = `第 ${d.round} 轮`;
        if (d.focus) els.focus.textContent = '聚焦：' + d.focus;
        els.messages.insertAdjacentHTML('beforeend',
          `<div class="round-sep"><span>第 ${d.round} 轮</span></div>`);
        break;
      case 'focus':
        els.focus.textContent = '聚焦：' + d.focus;
        break;
      case 'speaker_start':
        if (d.speaker !== 'host') {
          states[d.speaker] = { status: 'speaking', thought: '发言中…' };
          renderAgents();
        }
        startMsg(d);
        break;
      case 'delta':
        if (current && current.id === d.speaker) {
          current.text += d.text;
          current.txt.textContent = current.text;
          els.messages.scrollTop = els.messages.scrollHeight;
        }
        break;
      case 'speaker_end':
        endMsg();
        if (d.speaker && d.speaker !== 'host') {
          states[d.speaker] = { status: 'standby', thought: '待机中' };
          renderAgents();
        }
        break;
      case 'stance':
        if (d.shift !== 'hold') {
          const last = els.messages.querySelector('.msg:last-child .who');
          if (last) last.insertAdjacentHTML('beforeend',
            `<span class="tag ${d.shift}">${d.shift === 'change' ? '立场改变' : '立场松动'}</span>`);
        }
        break;
      case 'insight':
        renderInsights(d.consensus || [], d.disagreements || []);
        break;
      case 'error':
        els.status.textContent = `⚠️ ${d.message}${d.recoverable ? '（可刷新重试）' : ''}`;
        break;
      case 'done':
        els.status.textContent = d.replay ? '回放结束（历史记录）' : '本场结束';
        if (d.summary) {
          els.messages.insertAdjacentHTML('beforeend',
            `<div class="summary-box"><div class="ins-title">主持人总结</div><div>${esc(d.summary)}</div></div>`);
        }
        es.close();
        break;
    }
  }

  const es = new EventSource(`${API}/api/debates/${debateId}/stream`);
  es.onmessage = e => { try { onEvent(JSON.parse(e.data)); } catch (_) {} };
  es.onerror = () => { els.status.textContent = '连接中断，正在重连…'; };
}

/* ---------------- 路由 ---------------- */
function route() {
  const h = location.hash.replace(/^#/, '') || '/';
  document.querySelectorAll('.nav a').forEach(a => {
    const target = a.getAttribute('href').replace('#', '');
    a.classList.toggle('active', h === target || (target !== '/' && h.startsWith(target)));
  });
  if (h === '/' || h === '') return renderHome();
  if (h === '/create') return renderCreate();
  if (h === '/archive') return renderArchive();
  const m = h.match(/^\/live\/(.+)$/);
  if (m) return renderStudio(m[1]);
  renderHome();
}
window.addEventListener('hashchange', route);

(async function init() {
  try {
    const h = await getJSON('/api/health');
    document.getElementById('mode').textContent =
      h.mode === 'mock' ? 'Mock 流式（未配置 Key）' : `${h.model}`;
  } catch (_) {}
  route();
})();
