const $ = (id) => document.getElementById(id);
let defaultPrompt = '';
let presets = {};

function toast(msg) {
  const el = $('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add('hidden'), 2800);
}

async function api(path, opts) {
  const res = await fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {}));
  let data = {};
  try { data = await res.json(); } catch (e) { /* 非 JSON 响应 */ }
  if (!res.ok) {
    const err = new Error(data.detail || ('请求失败（' + res.status + '）'));
    err.status = res.status;
    throw err;
  }
  return data;
}

function status(msg, kind) {
  const el = $('status');
  el.textContent = msg;
  el.className = 'status ' + (kind || '');
}

function showLogin() {
  $('adminShell').classList.add('hidden');
  $('loginScreen').classList.remove('hidden');
  $('loginPassword').value = '';
}

function showAdmin() {
  $('loginScreen').classList.add('hidden');
  $('adminShell').classList.remove('hidden');
}

async function doLogin() {
  const password = $('loginPassword').value;
  if (!password) { toast('请输入管理口令'); return; }
  $('loginBtn').disabled = true;
  try {
    const data = await api('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    if (data.role !== 'admin') { toast('这是访问口令，请输入后台管理口令'); return; }
    showAdmin();
    await loadConfig();
    await loadStats();
  } catch (err) {
    toast(err.message);
  } finally {
    $('loginBtn').disabled = false;
  }
}

async function loadConfig() {
  try {
    const cfg = await api('/api/config');
    defaultPrompt = cfg.default_system_prompt || '';
    presets = cfg.presets || {};
    const select = $('provider');
    select.innerHTML = Object.keys(presets).map((k) =>
      '<option value="' + k + '">' + presets[k].label + '</option>').join('');
    select.value = cfg.provider || 'custom';
    $('baseUrl').value = cfg.base_url || '';
    $('model').value = cfg.model || '';
    $('apiKey').value = '';
    $('temperature').value = cfg.temperature;
    $('maxTokens').value = cfg.max_tokens;
    $('timeout').value = cfg.timeout;
    $('jsonMode').checked = !!cfg.json_mode;
    $('clearKey').checked = false;
    $('systemPrompt').value = cfg.system_prompt || defaultPrompt;
    $('keyState').textContent = cfg.api_key_set
      ? '已保存的 Key：' + cfg.api_key_masked + '（明文不会回传）'
      : '尚未保存 API Key（本地模型可留空）';
  } catch (err) {
    status(err.message, 'err');
  }
}

async function loadStats() {
  try {
    const s = await api('/api/stats');
    $('mCalls').textContent = s.calls;
    $('mSuccess').textContent = s.success;
    $('mFailed').textContent = s.rejected + s.failed;
    $('mAvg').textContent = Math.round(s.avg_ms / 1000) + 's';
    $('statNote').textContent = '仅统计本次容器运行期间，重启清零。累计 Token：' + (s.total_tokens || 0);
  } catch (e) { /* 统计失败不影响配置 */ }
}

function collect() {
  return {
    provider: $('provider').value,
    base_url: $('baseUrl').value.trim(),
    model: $('model').value.trim(),
    api_key: $('clearKey').checked ? '__CLEAR__' : $('apiKey').value.trim(),
    temperature: $('temperature').value,
    max_tokens: $('maxTokens').value,
    timeout: $('timeout').value,
    json_mode: $('jsonMode').checked,
    system_prompt: $('systemPrompt').value,
  };
}

async function save(silent) {
  try {
    const cfg = await api('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(collect()),
    });
    $('apiKey').value = '';
    $('clearKey').checked = false;
    $('keyState').textContent = cfg.api_key_set
      ? '已保存的 Key：' + cfg.api_key_masked + '（明文不会回传）'
      : '尚未保存 API Key（本地模型可留空）';
    if (!silent) status('配置已保存，下次点评立即生效', 'ok');
    return true;
  } catch (err) {
    status(err.message, 'err');
    return false;
  }
}

async function testConn() {
  status('正在保存并发起一次真实调用…');
  if (!(await save(true))) return;
  $('testBtn').disabled = true;
  try {
    const r = await api('/api/test-connection', { method: 'POST' });
    status('连接成功 · ' + r.model + ' · 耗时 ' + r.elapsed_ms + ' ms' + (r.preview ? ' · 模型回复：' + r.preview : ''), 'ok');
  } catch (err) {
    status('连接失败：' + err.message, 'err');
  } finally {
    $('testBtn').disabled = false;
    await loadStats();
  }
}

$('loginBtn').addEventListener('click', doLogin);
$('loginPassword').addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });
$('provider').addEventListener('change', (e) => {
  const p = presets[e.target.value];
  if (p && p.base_url) {
    $('baseUrl').value = p.base_url;
    $('model').value = p.model;
    status('已填入预设地址与常见型号，请以厂商文档核对', '');
  }
});
$('saveBtn').addEventListener('click', () => save(false));
$('testBtn').addEventListener('click', testConn);
$('resetPromptBtn').addEventListener('click', () => {
  $('systemPrompt').value = defaultPrompt;
  toast('已恢复默认，记得保存配置');
});

(async function boot() {
  try {
    const me = await api('/api/me');
    if (me.role !== 'admin') { location.href = '/'; return; }
    showAdmin();
    await loadConfig();
    await loadStats();
  } catch (err) {
    if (err.status === 401) showLogin();
    else toast(err.message);
  }
})();
