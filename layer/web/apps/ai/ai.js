/* AI Center: 24/7 AI jobs (serve models, train, scripts) with thermal guard and auto-resume. */
(function () {
  'use strict';
  const S = window.StarX, $ = S.$, esc = S.esc;
  let st = { jobs: [] }, tpls = [], logTimer = null, offline = '';
  const stateChip = { running: 'good', queued: 'accent', waiting: 'accent', paused: 'warn', failed: 'bad', finished: 'good', stopped: '' };
  const stateText = { running: 'Running', queued: 'Queued', waiting: 'Waiting for night', paused: 'Paused to cool down', failed: 'Failed', finished: 'Finished', stopped: 'Stopped' };

  async function refresh() {
    try { st = await S.call('ai.status'); offline = st.offline || ''; } catch (e) { offline = e.message; }
    try { const p = await S.call('power.get'); $('#t247').setAttribute('aria-checked', String(!!p.ai_247)); } catch (e) { }
    render();
  }

  function render() {
    const running = (st.jobs || []).filter(j => j.state === 'running').length;
    $('#stats').innerHTML = `<div><span>Temperature</span><b>${st.temp != null ? Math.round(st.temp) + '°C' : '–'}</b></div>
      <div><span>CPU</span><b>${st.cpu != null ? Math.round(st.cpu) + '%' : '–'}</b></div>
      <div><span>Memory</span><b>${st.mem_used ? S.bytes(st.mem_used) : '–'}</b></div>
      <div><span>Jobs running</span><b>${running}</b></div>`;
    const tl = st.thermal_limit || 75; $('#tl').value = tl; $('#tl-v').textContent = tl + '°C';
    $('#jobs').innerHTML = (offline ? `<div class="job"><b>AI service is not running.</b><div class="sub">${esc(offline)}</div></div>` : '') +
      ((st.jobs || []).map(j => `<div class="job" data-id="${esc(j.id)}">
        <div class="top"><b class="nm grow">${esc(j.name)}</b><span class="chip ${stateChip[j.state] || ''}">${stateText[j.state] || esc(j.state)}</span></div>
        <div class="sub">${esc(j.kind === 'serve' ? 'Serving a model' : j.kind === 'train' ? 'Training' : 'Script')} · ${j.runtime ? 'ran ' + S.duration(j.runtime) : 'not started'}${j.restarts ? ` · restarted ${j.restarts}×` : ''}${j.schedule === 'night' ? ' · runs at night' : ''}${j.message ? ' · ' + esc(j.message) : ''}</div>
        ${j.kind !== 'serve' ? `<div class="meter"><i style="width:${Math.max(0, Math.min(100, j.progress || 0))}%"></i></div>` : ''}
        <div class="acts">${j.state === 'running' ? `<button class="btn small" data-a="pause">${S.icon('pause')} Pause</button>` : ''}
          ${['paused', 'stopped', 'failed', 'finished'].includes(j.state) ? `<button class="btn small" data-a="resume">${S.icon('play')} ${j.state === 'paused' ? 'Resume' : 'Run again'}</button>` : ''}
          ${['running', 'paused', 'queued', 'waiting'].includes(j.state) ? `<button class="btn small" data-a="stop">${S.icon('stop')} Stop</button>` : ''}
          <button class="btn small" data-a="log">${S.icon('terminal')} Log</button>
          <button class="btn small danger" data-a="delete">${S.icon('trash')}</button></div></div>`).join('') ||
      (offline ? '' : `<div class="job"><b>No jobs yet.</b><div class="sub">Start one on the right. Jobs keep running when you close this window, and they come back after a restart or a power cut.</div></div>`));
  }

  async function loadTemplates() {
    try { tpls = await S.call('ai.templates'); } catch (e) { tpls = []; }
    $('#tpls').innerHTML = tpls.map((t, i) => `<button class="tpl" data-t="${i}"><span class="ti">${S.icon(t.icon || 'chip')}</span><span><b>${esc(t.name)}</b><div class="faint" style="font-size:12.5px">${esc(t.description)}</div></span></button>`).join('') ||
      '<div class="faint">Templates appear when the AI service is running.</div>';
  }

  function showForm(t) {
    const d = t.defaults || {};
    $('#form').innerHTML = `<div class="form" style="margin-top:10px">
      <label>Name<input class="field" id="f-name" value="${esc(d.name || t.name)}"></label>
      ${(t.fields || []).includes('script') ? `<label>Python script or command<input class="field" id="f-cmd" value="${esc(d.command || '')}" placeholder="/home/storm/train.py"></label>` : ''}
      ${(t.fields || []).includes('steps') ? `<label>Training steps<input class="field" id="f-steps" type="number" value="${d.steps || 3000}"></label>` : ''}
      <label>When<select class="field" id="f-sched"><option value="now">Start now</option><option value="night">Only at night (10 PM – 7 AM)</option></select></label>
      <label>Use up to this much CPU<select class="field" id="f-cpu"><option value="100">1 core</option><option value="200">2 cores</option><option value="300" selected>3 cores</option><option value="400">All 4 cores</option></select></label>
      <label>Keep it running<select class="field" id="f-restart"><option value="on-failure" selected>Restart if it crashes</option><option value="always">Always (24/7)</option><option value="never">Run once</option></select></label>
      <button class="btn primary" id="f-go">${S.icon('play')} Start</button></div>`;
    S.spring($('#form'), { y: 16, opacity: 0 }, { y: 0, opacity: 1 });
    $('#f-go').onclick = async () => {
      const job = { template: t.id, name: $('#f-name').value.trim() || t.name, schedule: $('#f-sched').value,
        cpu_quota: +$('#f-cpu').value, restart: $('#f-restart').value };
      if ($('#f-cmd')) job.command = $('#f-cmd').value.trim();
      if ($('#f-steps')) job.steps = +$('#f-steps').value;
      try { await S.call('ai.create', { job }); S.toast('Job started'); $('#form').innerHTML = ''; } catch (e) { S.toast(e.message); }
      refresh();
    };
  }

  async function showLog(id) {
    const m = S.h(`<div class="modal"><div class="box glass strong fixed-bg"><div class="row"><b class="grow">Log</b><button class="btn small" id="lclose">Close</button></div><pre id="lpre">Loading…</pre></div></div>`);
    document.body.appendChild(m); S.spring(m.firstElementChild, { scale: .9, opacity: 0 }, { scale: 1, opacity: 1 });
    const load = async () => { try { const r = await S.call('ai.log', { id, lines: 300 }); $('#lpre').textContent = r.text || '(empty)'; $('#lpre').scrollTop = 1e9; } catch (e) { $('#lpre').textContent = e.message; } };
    load(); logTimer = setInterval(load, 3000);
    m.addEventListener('click', e => { if (e.target === m || e.target.id === 'lclose') { clearInterval(logTimer); m.remove(); } });
  }

  document.body.addEventListener('click', async e => {
    const tb = e.target.closest('[data-t]'); if (tb) { showForm(tpls[+tb.dataset.t]); return; }
    const b = e.target.closest('[data-a]'); if (!b) return;
    const id = b.closest('.job').dataset.id;
    if (b.dataset.a === 'log') return showLog(id);
    try { await S.call('ai.action', { id, action: b.dataset.a }); } catch (err) { S.toast(err.message); }
    refresh();
  });
  $('#t247').addEventListener('click', async () => {
    const on = $('#t247').getAttribute('aria-checked') !== 'true';
    try { await S.call('power.ai247', { on }); S.toast(on ? '24/7 AI mode is on' : '24/7 AI mode is off'); } catch (e) { S.toast(e.message); }
    refresh();
  });
  $('#tl').addEventListener('input', () => { $('#tl-v').textContent = $('#tl').value + '°C'; });
  $('#tl').addEventListener('change', async () => { try { await S.call('ai.action', { id: '*', action: 'thermal', value: +$('#tl').value }); } catch (e) { S.toast(e.message); } });

  // refresh only while the window is visible (saves power)
  let timer = null;
  const loop = () => { clearInterval(timer); if (!document.hidden) { refresh(); timer = setInterval(refresh, 3000); } };
  document.addEventListener('visibilitychange', loop);
  loop(); loadTemplates();
})();
