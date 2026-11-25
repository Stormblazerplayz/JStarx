/* The dynamic island: clock + status, morphs for notifications, volume and live activities. */
(function () {
  'use strict';
  const S = window.StarX, $ = S.$;
  const island = $('#island');
  const SMALL = { w: 620, h: 52 }, BIG = { w: 620, h: 150 };
  let net = {}, power = {}, idle = false;
  let mode = 'compact', modeTimer = null;
  const queue = [];

  $('#logo').src = S.ctx.web + '/icons/jstarx-mark.svg';

  /* ---------- geometry helpers ---------- */
  function setSize(w, h) {
    island.style.width = w + 'px'; island.style.height = h + 'px';
    island.style.borderRadius = Math.min(h / 2, 30) + 'px';
  }
  function surface(big) {
    const s = big ? BIG : SMALL;
    S.send('shell.size', { surface: 'island', w: s.w, h: s.h, exclusive: SMALL.h });
  }
  function input() { /* opaque surface: no input region needed */ }
  let geo = null;
  function alignGlass() {
    const scr = S.ctx.screen || { width: innerWidth };
    const ox = geo ? geo.x : (scr.width - innerWidth) / 2, oy = geo ? geo.y : 0;
    S.wallBehind(ox, oy);
    S.alignGlass(island, ox, oy);
  }
  S.on('geometry', g => { geo = g; alignGlass(); S.repaint(); });
  window.addEventListener('resize', alignGlass);
  island.addEventListener('transitionend', e => { if (e.propertyName === 'width' || e.propertyName === 'height') { input(); alignGlass(); } });

  /* ---------- compact content ---------- */
  function compactWidth() {
    const act = $('#act').textContent.trim() ? $('#act').getBoundingClientRect().width + 10 : 0;
    const icons = $('#icons').getBoundingClientRect().width;
    return Math.round(10 + 20 + 10 + $('#time').getBoundingClientRect().width + 14 + act + icons + 16);
  }
  function renderCompact() {
    const sec = S.settings.island && S.settings.island.seconds;
    $('#time').textContent = S.time(new Date(), sec);
    const icons = [];
    const st = Shell.status;
    if (st.cast && st.cast.state === 'casting') icons.push(S.icon('display'));
    if (power.profile === 'saver') icons.push(S.icon('leaf'));
    else if (power.profile === 'performance') icons.push(S.icon('bolt'));
    if (S.settings.island && S.settings.island.dnd) icons.push(S.icon('bellOff'));
    const wired = (net.devices || []).some(d => d.type === 'ethernet' && String(d.state).startsWith('connected'));
    if (wired) icons.push(S.icon('ethernet'));
    else if (net.ssid) icons.push(S.icon('wifi'));
    else icons.push(S.icon('wifiOff'));
    $('#icons').innerHTML = icons.join('');

    // live activities: AI training progress, casting search
    let act = '';
    const ai = st.ai || {};
    const running = (ai.jobs || []).filter(j => j.state === 'running');
    if (running.length && (!S.settings.island || S.settings.island.ai_activity)) {
      const j = running[0]; const p = Math.max(0, Math.min(100, j.progress || 0));
      const c = 2 * Math.PI * 7;
      act = `<svg class="prog" viewBox="0 0 18 18"><circle cx="9" cy="9" r="7" fill="none" stroke="rgba(255,255,255,.18)" stroke-width="3"/>
        <circle cx="9" cy="9" r="7" fill="none" stroke="#FF9F43" stroke-width="3" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - p / 100)}"/></svg>
        ${S.esc(j.kind === 'serve' ? (j.name || 'AI') : `${(j.name || 'Training').slice(0, 14)} ${Math.round(p)}%`)}${ai.temp ? ` · ${Math.round(ai.temp)}°` : ''}`;
    } else if (st.cast && st.cast.state === 'searching') {
      act = `${S.icon('display')} Finding a display…`;
    } else if (st.cast && st.cast.state === 'casting') {
      act = `${S.icon('display')} ${S.esc((st.cast.device || 'TV').slice(0, 16))}`;
    } else if (st.update && st.update.state === 'downloading') {
      act = `${S.icon('download')} Updating…`;
    }
    $('#act').innerHTML = act;
    $('#logo').classList.toggle('busy', running.length > 0);
    if (mode === 'compact') { setSize(compactWidth(), 38); }
  }

  /* ---------- modes ---------- */
  function show(which, ms) {
    clearTimeout(modeTimer);
    mode = which;
    ['compact', 'note', 'osd'].forEach(m => $('#' + m).classList.toggle('on', m === which));
    $('#compact').classList.toggle('off', which !== 'compact');
    if (which === 'compact') {
      setSize(compactWidth(), 38);
      setTimeout(() => surface(false), 600);
      if (queue.length) setTimeout(() => showNote(queue.shift()), 700);
      return;
    }
    if (ms) modeTimer = setTimeout(() => show('compact'), ms);
  }

  function showNote(n) {
    if (mode === 'note') { queue.push(n); return; }
    surface(true);
    const ic = n.icon && S.iconNames.includes(n.icon) ? n.icon : (n.icon === 'jstarx' ? 'star' : 'bell');
    $('#note').innerHTML = `<div class="nicon">${S.icon(ic)}</div><div class="grow"><div class="napp">${S.esc(n.app)}</div>
      <div class="nsum">${S.esc(n.summary)}</div><div class="nbody">${S.esc(n.body)}</div></div>`;
    $('#note')._id = n.id;
    setTimeout(() => { setSize(500, 92); show('note', 5200); }, 30);
  }

  async function showOsd(kind) {
    surface(false);
    let level = 0, icon = 'volume';
    if (kind === 'volume') {
      try { const a = await S.call('audio.get'); level = a.muted ? 0 : a.volume; icon = a.muted || !level ? 'mute' : 'volume'; } catch (e) { }
    } else { icon = 'sun'; try { level = (await S.call('display.get')).backlight.level; } catch (e) { level = 100; } }
    $('#osd').innerHTML = `${S.icon(icon)}<div class="meter"><i style="width:${level}%"></i></div><span class="pct">${level}%</span>`;
    setSize(320, 44);
    show('osd', 1600);
  }

  island.addEventListener('click', () => {
    if (mode === 'note') {
      S.send('notifications.dismiss', { id: $('#note')._id });
      show('compact'); return;
    }
    const r = island.getBoundingClientRect();
    const scr = S.ctx.screen || { width: innerWidth };
    const ox = (scr.width - innerWidth) / 2;
    S.send('shell.open', { panel: 'control', data: { from: { left: r.left + ox, top: r.top, width: r.width, height: r.height } } });
  });

  /* ---------- data ---------- */
  async function refreshNet() {
    if (idle) return;
    try { net = await S.call('net.status'); } catch (e) { }
    renderCompact();
  }
  async function refreshPower() {
    try { power = await S.call('power.get'); } catch (e) { }
    renderCompact();
  }

  let hintTimer = null;
  S.on('hint', d => {
    clearTimeout(hintTimer);
    if (mode === 'note' || mode === 'osd') return;
    if (!d.text) { hintTimer = setTimeout(() => { if (mode === 'hint') show('compact'); }, 250); return; }
    $('#osd').innerHTML = `${S.icon('apps')}<b style="white-space:nowrap">${S.esc(d.text)}</b>`;
    mode = 'hint';
    ['compact', 'note'].forEach(m => $('#' + m).classList.remove('on'));
    $('#compact').classList.add('off'); $('#osd').classList.add('on');
    setSize(Math.max(150, 60 + d.text.length * 9), 38);
    hintTimer = setTimeout(() => { if (mode === 'hint') show('compact'); }, 2500);
  });
  S.on('notification', n => { if (!S.settings.island || S.settings.island.notifications !== false) showNote(n); });
  S.on('osd', d => showOsd(d.kind));
  S.on('status', st => { if (st.power) power = Object.assign({}, power, st.power); renderCompact(); });
  S.on('settings', renderCompact);
  S.on('idle', v => { idle = v; if (!v) refreshNet(); });
  S.on('overlay-state', st => { island.style.opacity = st.panel === 'control' ? '0' : '1'; });

  S.on('dim', d => document.body.classList.toggle('dimmed', !!d.on));

  (async function init() {
    try { Object.assign(Shell.status, (await S.call('shell.state')).status || {}); } catch (e) { }
    renderCompact();
    S.spring(island, { y: -60, scale: .6, opacity: 0 }, { y: 0, scale: 1, opacity: 1 }, { damping: .5, delay: 150 })
      .then(() => { island.style.transform = ''; input(); alignGlass(); });
    const sec = S.settings.island && S.settings.island.seconds;
    if (sec) setInterval(() => { if (!idle && mode === 'compact') $('#time').textContent = S.time(new Date(), true); }, 1000);
    S.everyMinute(() => { if (mode === 'compact') renderCompact(); });
    refreshNet(); setInterval(refreshNet, 30000);
    refreshPower();
    S.send('shell.ready');
  })();
})();
