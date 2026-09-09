// karyab review dashboard.
//
// Kept as a real file rather than inline in index.html: the inline version was
// edited by string replacement one time too many and ended up with four copies
// of the same block, which broke every script on the page and left the queue
// silently empty. A file can be syntax-checked, and tests/test_page_js.py does.

const $ = (s) => document.querySelector(s);
const fa = (n) => Number(n).toLocaleString('fa-IR');
const toman = (n) => (n ? fa(n) : '؟');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let items = [];
let autoTimer = null;
let pendingId = null;

// ---------- tabs ----------
function tab(which) {
  for (const [name, view, btn] of [
    ['queue', '#viewQueue', '#tabQueue'],
    ['applied', '#viewApplied', '#tabApplied'],
    ['settings', '#viewSettings', '#tabSettings'],
  ]) {
    const on = which === name;
    $(view).hidden = !on;
    $(btn).setAttribute('aria-current', String(on));
  }
  if (which === 'settings') loadSettings();
  if (which === 'applied') loadApplied();
}

// ---------- review queue ----------
async function loadQueue() {
  const r = await fetch('/api/queue?limit=40&rejected=' + $('#showRejected').checked);
  const d = await r.json();
  items = d.items || [];

  const cap = d.daily_cap || 0;
  const sent = d.sent_today || 0;
  $('#meterFill').style.width = cap ? Math.min(100, (sent / cap) * 100) + '%' : '0%';
  $('#meterText').textContent = `${fa(sent)} / ${fa(cap)} امروز · ${fa(d.tokens_today || 0)} ژتون`;
  $('#meter').title =
    `در ۲۴ ساعت گذشته ${fa(sent)} پیشنهاد فرستادید. ${fa(d.candidate_count || 0)} کاندیدا در صف است.`;

  if (!items.length) {
    $('#queueLede').textContent = '';
    $('#list').innerHTML =
      '<div class="empty"><p>هنوز چیزی در صف نیست.</p>' +
      '<p>دکمه‌ی «جستجوی پروژه‌های تازه» را بزنید.</p></div>';
    return;
  }
  const over = items.filter((i) => i.value >= d.threshold).length;
  $('#queueLede').textContent =
    `${fa(items.length)} پروژه بررسی شد، ${fa(over)} تا از آستانه‌ی ${fa(d.threshold)} گذشت.`;

  $('#list').innerHTML = items.map((it, i) => {
    const cls = it.rejected ? 'rej' : (it.value >= d.threshold ? '' : 'below');
    const why = (it.reasons || []).slice(0, 4).map((x) => `<span>${esc(x)}</span>`).join('');
    return `<article class="item" data-i="${i}">
      <div class="head">
        <div class="score ${cls} num">${fa(Math.round(it.value))}</div>
        <div style="flex:1;min-width:0">
          <h2 class="title">${esc(it.title)}</h2>
          <div class="facts">
            <span class="num">${toman(it.min_budget)}–${toman(it.max_budget)} تومان</span>
            <span class="cost num">${fa(it.token)} ژتون</span>
          </div>
          <div class="why">${why}</div>
        </div>
      </div>
      <div class="body">
        <div class="pane">
          <h3>پیش‌نویس شما</h3>
          <textarea data-draft="${i}" placeholder="اینجا بنویسید تا بررسی شود.">${esc(it.draft || '')}</textarea>
          <div class="verdict" data-verdict="${i}"></div>
          <div class="actions">
            <button class="act send" data-open="${i}">باز کردن آگهی</button>
            <button class="act done" data-applied="${it.project_id}">ارسال شد</button>
            <button class="tiny" data-brief="${it.project_id}">گرفتن بریف برای Claude</button>
            <button class="act skip" data-skip="${i}">رد کردن</button>
            <span class="saved" data-saved="${i}">ذخیره شد</span>
          </div>
          <div class="brief-box" data-briefbox="${it.project_id}"></div>
        </div>
        <div class="pane">
          <h3>شرح کارفرما</h3>
          <div class="brief">${esc(it.description || 'کارفرما شرحی ننوشته است.')}</div>
        </div>
      </div>
    </article>`;
  }).join('');

  wireCards();
}

function wireCards() {
  document.querySelectorAll('.head').forEach((h) => {
    h.onclick = () => h.closest('.item').classList.toggle('is-open');
  });
  document.querySelectorAll('[data-draft]').forEach((t) => {
    const pid = items[t.dataset.draft].project_id;
    let timer;
    t.oninput = () => {
      clearTimeout(timer);
      timer = setTimeout(() => check(t), 400);
      saveDraft(t, pid);
    };
    if (t.value.trim()) check(t);
  });
  document.querySelectorAll('[data-open]').forEach((b) => {
    b.onclick = () => openAd(items[b.dataset.open].slug);
  });
  document.querySelectorAll('[data-skip]').forEach((b) => {
    b.onclick = () => b.closest('.item').remove();
  });
  document.querySelectorAll('[data-applied]').forEach((b) => {
    b.onclick = async () => {
      await fetch('/api/applied/' + b.dataset.applied, { method: 'POST' });
      const card = b.closest('.item');
      card.style.opacity = '.35';
      setTimeout(() => { card.remove(); loadQueue(); }, 260);
    };
  });
  document.querySelectorAll('[data-brief]').forEach((b) => {
    b.onclick = async () => {
      const box = document.querySelector(`[data-briefbox="${b.dataset.brief}"]`);
      if (box.classList.contains('on')) { box.classList.remove('on'); return; }
      box.textContent = 'در حال آماده‌سازی…';
      box.classList.add('on');
      const d = await (await fetch('/api/brief/' + b.dataset.brief)).json();
      box.textContent = d.brief;
      try {
        await navigator.clipboard.writeText(d.brief);
        b.textContent = 'کپی شد — به Claude بدهید';
      } catch (e) { /* clipboard blocked; the text is still on screen */ }
    };
  });
}

function openAd(slug) {
  window.open('https://www.karlancer.com/projects/' + encodeURI(slug || ''), '_blank');
}

let saveTimer;
function saveDraft(area, projectId) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    await fetch('/api/draft/' + projectId, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: area.value }),
    });
    const tag = document.querySelector(`[data-saved="${area.dataset.draft}"]`);
    if (tag) { tag.classList.add('on'); setTimeout(() => tag.classList.remove('on'), 1400); }
  }, 700);
}

async function check(area) {
  const i = area.dataset.draft;
  const box = document.querySelector(`[data-verdict="${i}"]`);
  if (!area.value.trim()) { box.innerHTML = ''; return; }
  const d = await (await fetch('/api/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: area.value }),
  })).json();
  const blocking = d.blocking || [];
  const a = d.assessment || {};
  if (blocking.length) {
    box.innerHTML = '<div class="bad"><b>باید اصلاح شود:</b><ul>' +
      blocking.map((v) => `<li>${esc(v.message)}</li>`).join('') + '</ul></div>';
  } else {
    const w = (a.weaknesses || []).map((x) => `<li>${esc(x)}</li>`).join('');
    box.innerHTML =
      `<div class="good">امتیاز <b class="num">${fa(a.score)}</b> از ۱۰۰ · ${fa(a.word_count)} کلمه</div>` +
      (w ? `<ul style="color:var(--muted)">${w}</ul>` : '');
  }
}

// ---------- applied ----------
function when(iso) {
  if (!iso) return '';
  const mins = Math.round((Date.now() - new Date(iso)) / 60000);
  if (mins < 60) return `${fa(mins)} دقیقه پیش`;
  if (mins < 1440) return `${fa(Math.round(mins / 60))} ساعت پیش`;
  return `${fa(Math.round(mins / 1440))} روز پیش`;
}

async function loadApplied() {
  const d = await (await fetch('/api/applied')).json();
  const rows = d.items || [];
  if (!rows.length) {
    $('#appliedLede').textContent = '';
    $('#appliedList').innerHTML =
      '<div class="empty"><p>هنوز پیشنهادی ارسال نکرده‌اید.</p></div>';
    return;
  }
  $('#appliedLede').textContent =
    `${fa(rows.length)} پیشنهاد ارسال‌شده · مجموعا ${fa(d.total_tokens)} ژتون`;
  $('#appliedList').innerHTML = rows.map((it) => `
    <div class="applied-row">
      <div class="when num">${when(it.applied_at)}</div>
      <div style="flex:1;min-width:0">
        <div class="title" style="font-size:15px">${esc(it.title)}</div>
        <div class="facts">
          <span class="num">${toman(it.min_budget)}–${toman(it.max_budget)} تومان</span>
          <button class="tiny" data-unapply="${it.project_id}">برگرداندن به صف</button>
        </div>
        ${it.draft ? `<div class="sent">${esc(it.draft)}</div>` : ''}
      </div>
      <div><span class="cost num">${fa(it.token)} ژتون</span></div>
    </div>`).join('');
  document.querySelectorAll('[data-unapply]').forEach((b) => {
    b.onclick = async () => {
      await fetch('/api/applied/' + b.dataset.unapply, { method: 'DELETE' });
      loadApplied();
    };
  });
}

// ---------- settings ----------
async function loadSettings() {
  const d = await (await fetch('/api/settings')).json();
  $('#keyMask').textContent = d.api_key_masked;
}

function say(msg, ok) {
  const el = $('#keyState');
  el.className = 'state on ' + (ok ? 'ok' : 'err');
  el.textContent = msg;
}

// ---------- actions ----------
function busy(on, msg) {
  const el = $('#busy');
  el.hidden = !on;
  el.textContent = msg || '';
  $('#btnScan').disabled = on;
  $('#btnHarvest').disabled = on;
}

// ---------- auto mode ----------
function sheet(id, on) { $(id).classList.toggle('on', on); }

async function setAuto(on) {
  await fetch('/api/auto/enable?on=' + on, { method: 'POST' });
  $('#autoOn').checked = on;
  $('#autoBtn').classList.toggle('on', on);
  clearInterval(autoTimer);
  if (on) { autoTick(); autoTimer = setInterval(autoTick, 20000); }
  else { sheet('#approve', false); pendingId = null; }
}

async function autoTick() {
  const d = await (await fetch('/api/auto')).json();
  if (!d.enabled) return;
  $('#queueLede').textContent =
    `حالت خودکار روشن است — ${fa(d.sent_today)} از ${fa(d.daily_cap)} امروز، ` +
    `${fa(d.queued)} در نوبت. ${d.reason || ''}`;

  if (d.action === 'scan') {
    busy(true, 'جستجوی خودکار');
    try { await fetch('/api/actions/scan?pages=2', { method: 'POST' }); } catch (e) { /* reported next tick */ }
    await fetch('/api/auto/scanned', { method: 'POST' });
    busy(false);
    await loadQueue();
    return;
  }
  if (d.action === 'await_approval' && d.pending && d.pending.project_id !== pendingId) {
    showApproval(d.pending);
  }
}

function showApproval(p) {
  pendingId = p.project_id;
  $('#apTitle').textContent = p.title;
  $('#apBudget').textContent = `${toman(p.min_budget)}–${toman(p.max_budget)} تومان`;
  $('#apToken').textContent = `${fa(p.token)} ژتون`;
  $('#apScore').textContent = `امتیاز ${fa(Math.round(p.score))}`;
  $('#apBrief').textContent = p.description || 'کارفرما شرحی ننوشته است.';
  $('#apDraft').value = p.draft || '';
  $('#apAmount').value = p.suggested_amount || '';
  $('#apSlug').value = p.slug || '';
  checkApproval();
  sheet('#approve', true);
}

async function checkApproval() {
  const text = $('#apDraft').value;
  const box = $('#apVerdict');
  if (!text.trim()) {
    box.innerHTML = '<div class="bad">هنوز متنی نوشته نشده. از «گرفتن بریف برای Claude» استفاده کنید.</div>';
    $('#apApprove').disabled = true;
    return;
  }
  const d = await (await fetch('/api/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })).json();
  const bad = d.blocking || [];
  $('#apApprove').disabled = bad.length > 0;
  box.innerHTML = bad.length
    ? '<div class="bad"><b>باید اصلاح شود:</b><ul>' +
      bad.map((v) => `<li>${esc(v.message)}</li>`).join('') + '</ul></div>'
    : `<div class="good">امتیاز <b class="num">${fa(d.assessment.score)}</b> از ۱۰۰ · ${fa(d.assessment.word_count)} کلمه</div>`;
}

// ---------- wiring ----------
function boot() {
  $('#tabQueue').onclick = () => { tab('queue'); loadQueue(); };
  $('#tabApplied').onclick = () => tab('applied');
  $('#tabSettings').onclick = () => tab('settings');
  $('#showRejected').onchange = loadQueue;

  $('#btnScan').onclick = async () => {
    busy(true, 'در حال جستجو');
    try {
      const r = await fetch('/api/actions/scan?pages=2', { method: 'POST' });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'ناموفق');
      await loadQueue();
    } catch (e) {
      $('#queueLede').textContent = 'جستجو ناموفق بود: ' + e.message;
    }
    busy(false);
  };

  $('#btnHarvest').onclick = async () => {
    busy(true, 'در حال خواندن سوابق');
    try {
      const r = await fetch('/api/actions/harvest', { method: 'POST' });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'ناموفق');
      $('#queueLede').textContent =
        `${fa(d.fetched)} پیشنهاد خوانده شد؛ ${fa(d.teachable)} نمونه‌ی برنده.`;
    } catch (e) {
      $('#queueLede').textContent = 'ناموفق: ' + e.message;
    }
    busy(false);
  };

  $('#keySave').onclick = async () => {
    const key = $('#keyInput').value.trim();
    if (!key) return say('کلید را وارد کنید.', false);
    const r = await fetch('/api/settings/api-key', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    });
    const d = await r.json();
    if (!r.ok) return say(d.detail || 'ذخیره نشد.', false);
    $('#keyInput').value = '';
    $('#keyMask').textContent = d.api_key_masked;
    say('ذخیره شد.', true);
  };
  $('#keyTest').onclick = async () => {
    say('در حال آزمایش…', true);
    const r = await fetch('/api/settings/api-key/test', { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    say(r.ok ? 'کلید کار می‌کند.' : (d.detail || 'کلید کار نکرد.'), r.ok);
  };
  $('#keyClear').onclick = async () => {
    const d = await (await fetch('/api/settings/api-key', { method: 'DELETE' })).json();
    $('#keyMask').textContent = d.api_key_masked;
    say('کلید حذف شد.', true);
  };

  $('#autoOn').onclick = (e) => {
    e.preventDefault();
    if ($('#autoOn').checked) setAuto(false);
    else sheet('#autoInfo', true);
  };
  $('#autoCancel').onclick = () => sheet('#autoInfo', false);
  $('#autoStart').onclick = () => { sheet('#autoInfo', false); setAuto(true); };

  let apTimer;
  $('#apDraft').oninput = () => { clearTimeout(apTimer); apTimer = setTimeout(checkApproval, 350); };

  $('#apApprove').onclick = async () => {
    const r = await fetch('/api/auto/approve/' + pendingId, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: $('#apDraft').value, amount: Number($('#apAmount').value) || 0 }),
    });
    if (!r.ok) { const e = await r.json(); alert(e.detail || 'تایید نشد'); return; }
    openAd($('#apSlug').value);
    sheet('#approve', false);
    pendingId = null;
    $('#queueLede').textContent =
      'صفحه‌ی ثبت باز شد. متن و مبلغ را وارد کنید، سطح پیشنهاد را انتخاب کنید، بعد «ارسال شد» را بزنید.';
  };
  $('#apSkip').onclick = async () => {
    await fetch('/api/auto/skip/' + pendingId, { method: 'POST' });
    sheet('#approve', false);
    pendingId = null;
    loadQueue();
  };
  $('#apLater').onclick = () => sheet('#approve', false);

  loadQueue();
}

document.addEventListener('DOMContentLoaded', boot);
