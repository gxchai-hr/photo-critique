const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let selectedFile = null;
let previewUrl = null;
let controller = null;
let stepTimer = null;
let lastResultText = '';

function toast(msg, ms) {
  const el = $('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add('hidden'), ms || 2800);
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

function showScreen(id) {
  ['screenUpload', 'screenLoading', 'screenResult', 'screenReject'].forEach((name) => {
    $(name).classList.toggle('hidden', name !== id);
  });
  window.scrollTo(0, 0);
}

function showLogin() {
  $('appShell').classList.add('hidden');
  $('loginScreen').classList.remove('hidden');
  $('loginPassword').value = '';
}

function enterApp(role) {
  $('loginScreen').classList.add('hidden');
  $('appShell').classList.remove('hidden');
  $('adminLink').classList.toggle('hidden', role !== 'admin');
  showScreen('screenUpload');
}

async function boot() {
  try {
    const me = await api('/api/me');
    enterApp(me.role);
  } catch (err) {
    if (err.status === 401) showLogin();
    else toast(err.message);
  }
}

async function doLogin() {
  const password = $('loginPassword').value;
  if (!password) { toast('请输入口令'); return; }
  $('loginBtn').disabled = true;
  try {
    const data = await api('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    enterApp(data.role);
  } catch (err) {
    toast(err.message);
  } finally {
    $('loginBtn').disabled = false;
  }
}

function releasePreview() {
  if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
}

function setFile(file) {
  if (!file) return;
  const name = (file.name || '').toLowerCase();
  const looksImage = (file.type || '').startsWith('image/') || /\.(jpe?g|png|webp|heic|heif|avif)$/.test(name);
  if (!looksImage) { toast('请选择图片文件'); return; }
  if (file.size > 20 * 1024 * 1024) { toast('图片超过 20MB，请先压缩'); return; }
  releasePreview();
  selectedFile = file;
  previewUrl = URL.createObjectURL(file);
  $('previewImg').src = previewUrl;
  $('fileName').textContent = file.name + ' · ' + Math.round(file.size / 1024) + ' KB';
  $('previewWrap').classList.remove('hidden');
}

function clearFile() {
  releasePreview();
  selectedFile = null;
  $('fileInput').value = '';
  $('previewImg').removeAttribute('src');
  $('previewWrap').classList.add('hidden');
}

function startProgress() {
  let pct = 8;
  $('progressBar').style.width = pct + '%';
  $('dot1').className = 'dot active';
  $('step1').textContent = '进行中';
  $('dot2').className = 'dot';
  $('step2').textContent = '等待';
  clearInterval(stepTimer);
  stepTimer = setInterval(() => {
    pct = Math.min(88, pct + 4);
    $('progressBar').style.width = pct + '%';
    if (pct >= 36) {
      $('dot1').className = 'dot done';
      $('step1').textContent = '完成';
      $('dot2').className = 'dot active';
      $('step2').textContent = '进行中';
    }
  }, 1500);
}

function stopProgress(done) {
  clearInterval(stepTimer);
  stepTimer = null;
  $('progressBar').style.width = done ? '100%' : '8%';
}

async function submit() {
  if (!selectedFile) { toast('先选一张照片'); return; }
  const payload = new FormData();
  payload.append('image', selectedFile);
  payload.append('title', $('titleInput').value.trim());
  controller = new AbortController();
  $('submitBtn').disabled = true;
  $('loadImg').src = previewUrl || '';
  $('loadPreview').classList.remove('hidden');
  showScreen('screenLoading');
  startProgress();
  try {
    const data = await api('/api/review', { method: 'POST', body: payload, signal: controller.signal });
    stopProgress(true);
    if (!data.result.is_photograph) {
      $('rejectReason').textContent = data.result.reject_reason || '';
      showScreen('screenReject');
    } else {
      renderResult(data);
    }
  } catch (err) {
    stopProgress(false);
    if (err.name === 'AbortError') {
      toast('已取消');
    } else {
      toast(err.message, 4200);
    }
    showScreen('screenUpload');
  } finally {
    controller = null;
    $('submitBtn').disabled = false;
  }
}

function renderResult(data) {
  const r = data.result;
  const warnings = data.warnings || [];
  const lines = [];
  lines.push('你拍我评');
  lines.push('综合评分：' + r.score + ' / 100');
  if (r.score_reason) lines.push('评分说明：' + r.score_reason);

  let html = '<div class="score-card">';
  html += '<span class="score-num">' + Number(r.score) + '</span><span class="score-denom">/ 100</span>';
  html += '<span class="score-reason">' + esc(r.score_reason) + '</span></div>';

  const chips = Object.keys(r.score_breakdown || {}).map((k) =>
    '<span class="chip">' + esc(k) + ' ' + Number(r.score_breakdown[k]) + '</span>').join('');
  if (chips) html += '<div class="chips">' + chips + '</div>';

  if (r.ai_suspect) {
    html += '<div class="banner banner-amber"><strong>疑似 AI 生成或生成式填充，已按规则降档</strong>';
    if (r.ai_evidence) html += '<p>' + esc(r.ai_evidence) + '</p>';
    html += '<p>评分已在常规判断基础上扣减，真实性与艺术感染力因此受损。</p></div>';
    lines.push('疑似 AI 生成或生成式填充，已按规则降档');
    if (r.ai_evidence) lines.push(r.ai_evidence);
  }
  if (warnings.length) {
    html += '<div class="banner banner-blue"><strong>提示</strong>' + warnings.map((w) => '<p>' + esc(w) + '</p>').join('') + '</div>';
  }

  if (r.first_impression) {
    html += section('第一眼印象', '<p class="section-body">' + esc(r.first_impression) + '</p>');
    lines.push('', '第一眼印象', r.first_impression);
  }
  if (r.subject) lines.push('画面主体：' + r.subject);

  if (Array.isArray(r.title_analysis) && r.title_analysis.length) {
    html += section('标题设计分析', r.title_analysis.map((t) =>
      '<div class="item">' + esc(t) + '</div>').join(''));
    lines.push('', '标题设计分析', ...r.title_analysis.map((t, i) => (i + 1) + '. ' + t));
  }

  html += section('技术亮点 · ' + r.highlights.length, r.highlights.map((h, i) =>
    '<div class="item good">' + (i + 1) + '. ' + esc(h.point) +
    (h.evidence ? '<span class="evidence">' + esc(h.evidence) + '</span>' : '') + '</div>').join(''));
  lines.push('', '技术亮点', ...r.highlights.map((h, i) => (i + 1) + '. ' + h.point + (h.evidence ? '｜' + h.evidence : '')));

  html += section('核心问题 · ' + r.problems.length, r.problems.map((p, i) =>
    '<div class="item bad">' + (i + 1) + '. ' + esc(p.point) +
    (p.evidence ? '<span class="evidence">' + esc(p.evidence) + '</span>' : '') + '</div>').join(''));
  lines.push('', '核心问题', ...r.problems.map((p, i) => (i + 1) + '. ' + p.point + (p.evidence ? '｜' + p.evidence : '')));

  html += section('针对性修改建议', '<ol class="plain-list">' +
    r.suggestions.map((s) => '<li>' + esc(s) + '</li>').join('') + '</ol>');
  lines.push('', '针对性修改建议', ...r.suggestions.map((s, i) => (i + 1) + '. ' + s));

  html += '<p class="hint">评分为模型主观判断，仅供参考 · 本次耗时 ' +
    Math.round((data.elapsed_ms || 0) / 1000) + ' 秒</p>';
  html += '<div class="btn-row"><button id="copyBtn" class="btn">复制全文</button>' +
    '<button id="againBtn" class="btn btn-primary">再评一张</button></div>';

  lastResultText = lines.join('\n');
  $('screenResult').innerHTML = html;
  $('copyBtn').addEventListener('click', copyAll);
  $('againBtn').addEventListener('click', () => { clearFile(); $('titleInput').value = ''; showScreen('screenUpload'); });
  showScreen('screenResult');
}

function section(title, body) {
  return '<div class="section"><p class="section-title">' + esc(title) + '</p>' + body + '</div>';
}

async function copyAll() {
  try {
    await navigator.clipboard.writeText(lastResultText);
    toast('全文已复制');
  } catch (e) {
    const box = document.createElement('textarea');
    box.value = lastResultText;
    box.style.position = 'absolute';
    box.style.left = '-9999px';
    document.body.appendChild(box);
    box.select();
    try { document.execCommand('copy'); toast('全文已复制'); } catch (err) { toast('复制失败，请手动选择文字'); }
    document.body.removeChild(box);
  }
}

$('loginBtn').addEventListener('click', doLogin);
$('loginPassword').addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });
$('logoutBtn').addEventListener('click', async () => {
  try { await api('/api/logout', { method: 'POST' }); } catch (e) { /* 忽略 */ }
  showLogin();
});
$('dropzone').addEventListener('click', () => $('fileInput').click());
$('fileInput').addEventListener('change', (e) => setFile(e.target.files[0]));
$('clearBtn').addEventListener('click', (e) => { e.stopPropagation(); clearFile(); });
$('submitBtn').addEventListener('click', submit);
$('cancelBtn').addEventListener('click', () => { if (controller) controller.abort(); });
$('retryFromReject').addEventListener('click', () => { clearFile(); showScreen('screenUpload'); });
document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('drop', (e) => {
  e.preventDefault();
  if (!$('screenUpload').classList.contains('hidden') && e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});

boot();
