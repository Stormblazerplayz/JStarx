/* Overlay: Launchpad, Start menu, Control Center, Ask Spark, Power menu, Welcome. */
(function () {
  'use strict';
  const S = window.StarX, $ = S.$;
  let current = null, closing = false, home = { items: [] };
  const scrim = $('#scrim');

  /* ================================================================ open / close */
  async function open(panel, data) {
    if (current && current !== panel) hidePanel(current, true);
    current = panel; closing = false;
    if (!Shell.apps.length) await Shell.loadApps();
    scrim.className = panel === 'launchpad' ? 'lp' : '';
    requestAnimationFrame(() => scrim.classList.add('on'));
    ({ launchpad: openLaunchpad, start: openStart, control: openControl, spark: openSpark, power: openPower, welcome: openWelcome }[panel] || (() => {}))(data || {});
  }
  function elFor(panel) { return panel === 'power' ? $('#power-wrap') : panel === 'welcome' ? $('#welcome-wrap') : $('#' + panel); }
  function hidePanel(panel, instant) { const el = elFor(panel); if (el) el.classList.add('hidden'); if (panel === 'launchpad') $('#lp-folder').classList.add('hidden'); }

  async function close() {
    if (closing) return;
    if (!current) { S.send('shell.close'); return; }  // never leave an empty overlay on screen
    closing = true;
    const panel = current;
    const el = panel === 'power' ? $('#power') : panel === 'welcome' ? $('#welcome') : $('#' + panel);
    scrim.classList.remove('on');
    const anim = {
      launchpad: () => S.spring($('#launchpad'), { scale: 1, opacity: 1 }, { scale: 1.08, opacity: 0 }, { damping: 1, stiffness: 520 }),
      start: () => S.spring(el, { y: 0, opacity: 1, scale: 1 }, { y: 40, opacity: 0, scale: .96 }, { damping: 1, stiffness: 520 }),
      control: () => controlFrom ? Shell.morphTo(el, controlFrom, { stiffness: 520 }) : S.spring(el, { opacity: 1 }, { opacity: 0, y: -20 }, { damping: 1 }),
      spark: () => S.spring(el, { y: 0, opacity: 1 }, { y: -30, opacity: 0 }, { damping: 1, stiffness: 520 }),
    }[panel] || (() => S.spring(el, { scale: 1, opacity: 1 }, { scale: .9, opacity: 0 }, { damping: 1, stiffness: 520 }));
    await anim();
    hidePanel(panel);
    if (el) { el.style.transform = ''; el.style.opacity = ''; }
    $('#launchpad').style.transform = ''; $('#launchpad').style.opacity = '';
    if (sparkReq) { S.send('spark.stop', { req: sparkReq }); sparkReq = null; }
    current = null; closing = false;
    S.send('shell.close');
  }
  scrim.addEventListener('click', close);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { if (!$('#lp-folder').classList.contains('hidden')) closeLpFolder(); else close(); } });
  S.on('overlay-open', d => open(d.panel, d.data));
  S.on('overlay-close-request', close);

  async function launch(id, el) {
    await Shell.launch(id, el);
    setTimeout(close, 180);
  }

  /* ================================================================ Launchpad */
  let lpPage = 0, lpPages = 1, lpSel = 0, lpItems = [];
  function lpLayout() {
    const cols = (S.settings.launchpad && S.settings.launchpad.columns) || 7;
    const vh = $('#lp-viewport').clientHeight || (innerHeight - 260);
    const rows = Math.max(2, Math.floor((vh + 34) / 140));
    return { cols, per: cols * rows };
  }
  async function openLaunchpad(data) {
    try { home = await S.call('home.get'); } catch (e) { }
    const lp = $('#launchpad'); lp.classList.remove('hidden');
    $('#lp-search').style.backgroundImage = `url("data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>')}")`;
    $('#lp-search').value = data.q || '';
    lpPage = 0; renderLaunchpad();
    S.spring(lp, { scale: 1.12, opacity: 0 }, { scale: 1, opacity: 1 }, { damping: .62, stiffness: 260 }).then(() => { lp.style.transform = ''; });
    const tiles = S.$$('.lp-page:first-child .app', lp);
    tiles.forEach((t, i) => S.spring(t, { scale: .7, y: 30, opacity: 0 }, { scale: 1, y: 0, opacity: 1 }, { delay: Math.min(i, 24) * 14, damping: .55 }));
    setTimeout(() => $('#lp-search').focus(), 50);
  }
  function lpEntries(q) {
    const t = (q || '').toLowerCase();
    // Launchpad shows every app (A to Z); folders live on the home screen.
    return Shell.apps.filter(a => !t || (a.name + ' ' + (a.description || '') + ' ' + a.category).toLowerCase().includes(t))
      .sort((a, b) => a.name.localeCompare(b.name)).map(a => ({ app: a }));
  }
  function renderLaunchpad() {
    const q = $('#lp-search').value.trim();
    lpItems = lpEntries(q);
    const { cols, per } = lpLayout();
    lpPages = Math.max(1, Math.ceil(lpItems.length / per));
    lpPage = Math.min(lpPage, lpPages - 1);
    lpSel = 0;
    const pages = [];
    for (let p = 0; p < lpPages; p++) {
      const slice = lpItems.slice(p * per, (p + 1) * per);
      pages.push(`<div class="lp-page" style="--cols:${cols}">${slice.map((it, i) =>
        (it.folder ? Shell.folderTile(it.folder) : Shell.tile(it.app)).replace('class="app', `class="app${p * per + i === lpSel && q ? ' sel' : ''}`)).join('') ||
        '<div class="lp-empty">No apps match. Try another word.</div>'}</div>`);
    }
    $('#lp-track').innerHTML = pages.join('');
    $('#lp-dots').innerHTML = lpPages > 1 ? Array.from({ length: lpPages }, (_, i) => `<button data-p="${i}" class="${i === lpPage ? 'on' : ''}" aria-label="Page ${i + 1}"></button>`).join('') : '';
    $('#lp-track').style.transform = `translateX(${-lpPage * 100}%)`;
  }
  function goPage(p) {
    p = Math.max(0, Math.min(lpPages - 1, p)); if (p === lpPage) return;
    const from = -lpPage * $('#lp-viewport').clientWidth, to = -p * $('#lp-viewport').clientWidth;
    lpPage = p;
    S.spring($('#lp-track'), { x: from }, { x: to }, { damping: .72, stiffness: 240 });
    S.$$('#lp-dots button').forEach((b, i) => b.classList.toggle('on', i === p));
  }
  $('#lp-search').addEventListener('input', () => { lpPage = 0; renderLaunchpad(); });
  $('#lp-search').addEventListener('keydown', e => {
    if (e.key === 'Enter') { const first = lpItems[0]; if (first && first.app) launch(first.app.id); else if (first && first.folder) openLpFolder(first.folder.id); }
    if (e.key === 'ArrowRight' && !$('#lp-search').value) goPage(lpPage + 1);
    if (e.key === 'ArrowLeft' && !$('#lp-search').value) goPage(lpPage - 1);
  });
  $('#lp-dots').addEventListener('click', e => { const b = e.target.closest('button'); if (b) goPage(+b.dataset.p); });
  let wheelLock = 0;
  $('#launchpad').addEventListener('wheel', e => {
    const now = Date.now(); if (now < wheelLock) return; wheelLock = now + 450;
    goPage(lpPage + ((e.deltaY || e.deltaX) > 0 ? 1 : -1));
  }, { passive: true });
  let swipe = null;
  $('#lp-viewport').addEventListener('pointerdown', e => { swipe = { x: e.clientX, t: Date.now() }; });
  $('#lp-viewport').addEventListener('pointerup', e => {
    if (!swipe) return; const dx = e.clientX - swipe.x; swipe = null;
    if (Math.abs(dx) > 80) { goPage(lpPage + (dx < 0 ? 1 : -1)); e.stopPropagation(); }
  });
  $('#launchpad').addEventListener('click', e => {
    const t = e.target.closest('.app');
    if (t && t.dataset.app) launch(t.dataset.app, t);
    else if (t && t.dataset.folder) openLpFolder(t.dataset.folder, t);
    else if (e.target === $('#launchpad') || e.target.classList.contains('lp-page') || e.target === $('#lp-viewport')) close();
  });

  let lpFolderFrom = null;
  function openLpFolder(id, tile) {
    const f = home.items.find(i => i.id === id); if (!f) return;
    lpFolderFrom = tile ? tile.querySelector('.icon').getBoundingClientRect() : null;
    const host = $('#lp-folder'); host.classList.remove('hidden');
    host.innerHTML = `<div class="fpanel glass strong fixed-bg"><h2>${S.esc(f.name)}</h2><div class="fgrid">${f.apps.map(a => Shell.tile(Shell.byId[a])).join('')}</div></div>`;
    Shell.morphFrom($('.fpanel', host), lpFolderFrom, { stiffness: 340 });
    S.$$('.fgrid .app', host).forEach((a, i) => S.spring(a, { scale: .5, opacity: 0 }, { scale: 1, opacity: 1 }, { delay: 80 + i * 35 }));
  }
  function closeLpFolder() {
    const host = $('#lp-folder'); const p = $('.fpanel', host); if (!p) { host.classList.add('hidden'); return; }
    Shell.morphTo(p, lpFolderFrom).then(() => { host.classList.add('hidden'); host.innerHTML = ''; });
  }
  $('#lp-folder').addEventListener('click', e => {
    const t = e.target.closest('.app');
    if (t && t.dataset.app) { launch(t.dataset.app, t); return; }
    if (e.target === $('#lp-folder')) closeLpFolder();
  });

  /* ================================================================ Start menu */
  async function openStart() {
    const el = $('#start'); el.classList.remove('hidden');
    const dockZone = ((S.settings.dock && S.settings.dock.size) || 54) + 30;
    el.style.bottom = (dockZone + 14) + 'px';
    const name = (S.settings.user && S.settings.user.name) || 'Friend';
    const pinnedOrder = ['firefox', 'spark', 'claude', 'ai', 'settings', 'store', 'terminal', 'snake', 'dodge', 'breaker'];
    const pins = pinnedOrder.map(id => Shell.byId[id]).filter(Boolean).concat(Shell.apps.filter(a => !pinnedOrder.includes(a.id))).slice(0, 12);
    el.innerHTML = `
      <input class="field search" id="start-q" placeholder="Search apps and settings" autocomplete="off">
      <div id="start-body">
        <div class="sec"><h3>Pinned</h3><button class="btn small" id="all-apps">All apps ${S.icon('chevronR')}</button></div>
        <div class="pins">${pins.map(a => Shell.tile(a)).join('')}</div>
        <div class="sec"><h3>For you</h3></div>
        <div class="recs" id="recs"></div>
      </div>
      <div class="foot"><span class="avatar">${S.esc(name[0].toUpperCase())}</span><b class="grow">${S.esc(name)}</b>
        <button class="iconbtn" id="st-settings" title="Settings">${S.icon('settings')}</button>
        <button class="iconbtn" id="st-power" title="Power">${S.icon('power')}</button></div>`;
    S.spring(el, { y: 60, opacity: 0, scale: .94 }, { y: 0, opacity: 1, scale: 1 }, { damping: .6 }).then(() => { el.style.transform = ''; });
    renderRecs();
    $('#start-q').focus();
    $('#start-q').addEventListener('input', startSearch);
    $('#start-q').addEventListener('keydown', e => { if (e.key === 'Enter') { const r = $('.result', el); if (r) r.click(); } });
    $('#all-apps').addEventListener('click', () => open('launchpad'));
    $('#st-settings').addEventListener('click', () => launch('settings'));
    $('#st-power').addEventListener('click', () => open('power'));
    el.onclick = e => { const t = e.target.closest('.app,.result'); if (t && t.dataset.app) launch(t.dataset.app, t); };
  }
  async function renderRecs() {
    const recs = [];
    let spark = {}; try { spark = await S.call('spark.status'); } catch (e) { }
    if (spark.engine !== 'ok') recs.push({ icon: 'sparkle', t: 'Set up Spark 1', s: 'Install your assistant\'s brain', app: 'settings' });
    else recs.push({ icon: 'sparkle', t: 'Ask Spark', s: 'Spark 1 is ready', panel: 'spark' });
    recs.push({ icon: 'bag', t: 'Get more apps', s: 'Official apps in Star Store', app: 'store' });
    recs.push({ icon: 'chip', t: 'AI Center', s: 'Run and train AI 24/7', app: 'ai' });
    const up = Shell.status.update || {};
    recs.push(up.available ? { icon: 'download', t: 'Update ready', s: `Version ${up.available}`, app: 'settings' } :
      { icon: 'shield', t: 'JStarx is healthy', s: 'Auto-repair is on', app: 'settings' });
    const box = $('#recs'); if (!box) return;
    box.innerHTML = recs.map((r, i) => `<button class="rec" data-i="${i}"><span class="ri">${S.icon(r.icon)}</span><span><div class="rt">${S.esc(r.t)}</div><div class="rs">${S.esc(r.s)}</div></span></button>`).join('');
    box.onclick = e => { const b = e.target.closest('.rec'); if (!b) return; const r = recs[+b.dataset.i]; if (r.panel) open(r.panel); else launch(r.app); };
  }
  function startSearch() {
    const q = $('#start-q').value.trim().toLowerCase();
    const body = $('#start-body');
    if (!q) { $('#start').querySelector('.results') && openStart(); return; }
    const hits = Shell.apps.filter(a => (a.name + ' ' + a.description + ' ' + a.category).toLowerCase().includes(q));
    body.innerHTML = `<div class="sec"><h3>Results</h3></div><div class="results scroll">${hits.map((a, i) =>
      `<button class="result ${i === 0 ? 'sel' : ''}" data-app="${S.esc(a.id)}"><img src="${S.esc(S.appIcon(a))}" alt=""><span><b>${S.esc(a.name)}</b><div class="faint" style="font-size:12.5px">${S.esc(a.description || a.category)}</div></span></button>`).join('') ||
      '<div class="faint" style="padding:12px">Nothing found.</div>'}</div>`;
  }

  /* ================================================================ Control center */
  let controlFrom = null, ccTimer = null;
  async function openControl(data) {
    controlFrom = data.from || null;
    const el = $('#control'); el.classList.remove('hidden');
    el.innerHTML = '<div class="tiles" id="cc-tiles"></div><div id="cc-rest"></div>';
    await renderControl();
    if (controlFrom) Shell.morphFrom(el, controlFrom, { stiffness: 300, damping: .62 }).then(() => { el.style.transform = ''; });
    else S.spring(el, { y: -40, opacity: 0 }, { y: 0, opacity: 1 }).then(() => { el.style.transform = ''; });
    clearInterval(ccTimer); ccTimer = setInterval(() => { if (current === 'control') renderStats(); else clearInterval(ccTimer); }, 4000);
  }
  async function renderControl() {
    const s = S.settings;
    let net = {}, power = {}, audio = {}, disp = {};
    await Promise.all([
      S.call('net.status').then(v => net = v).catch(() => { }),
      S.call('power.get').then(v => power = v).catch(() => { }),
      S.call('audio.get').then(v => audio = v).catch(() => { }),
      S.call('display.get').then(v => disp = v).catch(() => { }),
    ]);
    const cast = Shell.status.cast || {};
    const profileNames = { low: 'Low power', saver: 'Power saver', balanced: 'Balanced', performance: 'Performance', extreme: 'Extreme' };
    const tiles = [
      { id: 'wifi', icon: net.wifi_on === false ? 'wifiOff' : 'wifi', t: 'Wi-Fi', st: net.ssid || (net.wifi_on === false ? 'Off' : 'Not connected'), on: net.wifi_on !== false },
      { id: 'dnd', icon: s.island && s.island.dnd ? 'bellOff' : 'bell', t: 'Do Not Disturb', st: s.island && s.island.dnd ? 'On' : 'Off', on: !!(s.island && s.island.dnd) },
      { id: 'power', icon: (power.profile === 'saver' || power.profile === 'low') ? 'leaf' : (power.profile === 'performance' || power.profile === 'extreme') ? 'bolt' : 'gauge', t: 'Power mode', st: profileNames[power.profile] || 'Balanced', on: true },
      { id: 'ai247', icon: 'chip', t: 'AI 24/7', st: power.ai_247 ? 'Always on' : 'Off', on: !!power.ai_247 },
      { id: 'cast', icon: 'display', t: 'Cast screen', st: cast.state === 'casting' ? (cast.device || 'Casting') : (disp.casting ? 'To a TV or display' : 'Not available'), on: cast.state === 'casting' },
      { id: 'spark', icon: 'sparkle', t: 'Ask Spark', st: 'Your assistant', on: false },
    ];
    $('#cc-tiles').innerHTML = tiles.map(t => `<button class="tile ${t.on ? 'on' : ''}" data-t="${t.id}"><span class="ti">${S.icon(t.icon)}</span><span><div class="tt">${t.t}</div><div class="ts">${S.esc(t.st)}</div></span></button>`).join('');
    $('#cc-tiles').onclick = e => { const b = e.target.closest('.tile'); if (b) { S.boing(b, .06); tileAction(b.dataset.t, power, net); } };
    $('#cc-rest').innerHTML = `
      <div class="cc-block"><div class="cc-row">${S.icon(audio.muted ? 'mute' : 'volume')}<input type="range" class="slider" id="vol" min="0" max="100" value="${audio.volume || 0}" ${audio.available ? '' : 'disabled'}><b id="vol-v" style="width:40px;text-align:right">${audio.available ? audio.volume + '%' : '–'}</b></div></div>
      <div class="cc-block"><div class="stats" id="cc-stats"></div><div id="cc-jobs"></div></div>
      <div class="cc-block"><div class="cc-row" style="justify-content:space-between;margin-bottom:8px"><b>Notifications</b><button class="btn small" id="cc-clear">Clear all</button></div><div class="notes scroll" id="cc-notes"></div></div>
      <div class="cc-foot"><button class="btn grow" id="cc-settings">${S.icon('settings')} Settings</button><button class="btn" id="cc-power">${S.icon('power')}</button></div>`;
    const vol = $('#vol');
    vol.addEventListener('input', () => { $('#vol-v').textContent = vol.value + '%'; });
    vol.addEventListener('change', () => S.send('audio.set', { volume: +vol.value, muted: false }));
    $('#cc-clear').addEventListener('click', () => { S.send('notifications.clear'); $('#cc-notes').innerHTML = '<div class="faint">No notifications</div>'; });
    $('#cc-settings').addEventListener('click', () => launch('settings'));
    $('#cc-power').addEventListener('click', () => open('power'));
    renderStats(); renderNotes();
  }
  async function tileAction(id, power, net) {
    try {
      if (id === 'wifi') { await S.call('net.wifi_radio', { on: net.wifi_on === false }); }
      else if (id === 'dnd') { S.applySettings(await S.call('settings.set', { path: 'island.dnd', value: !(S.settings.island && S.settings.island.dnd) })); }
      else if (id === 'power') { const order = ['low', 'saver', 'balanced', 'performance', 'extreme']; const next = order[(order.indexOf(power.profile || 'balanced') + 1) % order.length]; await S.call('power.set', { profile: next }); }
      else if (id === 'ai247') { await S.call('power.ai247', { on: !power.ai_247 }); }
      else if (id === 'cast') { await S.call('display.cast'); close(); return; }
      else if (id === 'spark') { open('spark'); return; }
    } catch (e) { S.toast(e.message); }
    renderControl();
  }
  async function renderStats() {
    if (!$('#cc-stats')) return;
    try {
      const st = await S.call('system.stats');
      const mem = st.memory.total ? Math.round(100 * st.memory.used / st.memory.total) : 0;
      $('#cc-stats').innerHTML = `<div>CPU<b>${Math.round(st.cpu)}%</b></div><div>Memory<b>${mem}%</b></div><div>Temp<b>${st.temp == null ? '–' : Math.round(st.temp) + '°C'}</b></div>`;
    } catch (e) { }
    const jobs = ((Shell.status.ai || {}).jobs || []).filter(j => j.state === 'running' || j.state === 'paused').slice(0, 3);
    $('#cc-jobs').innerHTML = jobs.map(j => `<div class="job"><div class="jn"><span>${S.esc(j.name)}</span><span>${j.state === 'paused' ? 'Paused (cooling)' : Math.round(j.progress || 0) + '%'}</span></div><div class="meter"><i style="width:${j.progress || 0}%"></i></div></div>`).join('');
  }
  async function renderNotes() {
    let notes = []; try { notes = await S.call('notifications.list'); } catch (e) { }
    $('#cc-notes').innerHTML = notes.slice(-6).reverse().map(n => `<div class="nrow">${S.icon('bell')}<div class="grow"><b>${S.esc(n.summary)}</b><div>${S.esc(n.body)}</div></div></div>`).join('') || '<div class="faint">No notifications</div>';
  }

  /* ================================================================ Ask Spark */
  let sparkReq = null, sparkText = '';
  function openSpark(data) {
    const el = $('#spark'); el.classList.remove('hidden');
    el.innerHTML = `<form class="glass strong fixed-bg" id="spark-form"><img src="${S.ctx.web}/icons/spark.svg" alt=""><input id="spark-in" placeholder="Ask Spark 1 anything…" autocomplete="off"><button class="btn primary small">${S.icon('send')}</button></form>
      <div class="answer glass strong fixed-bg hidden scroll" id="spark-ans"></div>
      <div class="acts hidden" id="spark-acts"><button class="btn small" id="spark-open">${S.icon('sparkle')} Continue in Spark</button><button class="btn small" id="spark-setup">${S.icon('settings')} Spark settings</button></div>`;
    S.spring(el, { y: -50, opacity: 0, sx: .6 }, { y: 0, opacity: 1, sx: 1 }, { damping: .55 }).then(() => { el.style.transform = ''; });
    $('#spark-form').addEventListener('submit', e => { e.preventDefault(); ask($('#spark-in').value.trim()); });
    $('#spark-open').addEventListener('click', () => launch('spark'));
    $('#spark-setup').addEventListener('click', () => launch('settings'));
    setTimeout(() => $('#spark-in').focus(), 30);
    if (data.q) { $('#spark-in').value = data.q; ask(data.q); }
  }
  async function ask(q) {
    if (!q) return;
    const ans = $('#spark-ans');
    ans.classList.remove('hidden'); $('#spark-acts').classList.remove('hidden');
    sparkText = ''; ans.innerHTML = '<span class="cursor"></span>';
    S.spring(ans, { y: -20, opacity: 0, scale: .96 }, { y: 0, opacity: 1, scale: 1 });
    try { const r = await S.call('spark.chat', { messages: [{ role: 'user', content: q }] }); sparkReq = r.req; }
    catch (e) { ans.textContent = e.message; }
  }
  S.on('spark-token', d => {
    if (d.req !== sparkReq) return;
    sparkText += d.text;
    $('#spark-ans').innerHTML = S.esc(sparkText) + '<span class="cursor"></span>';
    $('#spark-ans').scrollTop = 1e9;
  });
  S.on('spark-done', d => {
    if (d.req !== sparkReq) return;
    sparkReq = null;
    $('#spark-ans').innerHTML = d.error ? `<b>Spark 1 isn't ready yet.</b>\n${S.esc(d.error)}` : S.esc(sparkText || '…');
  });

  /* ================================================================ Power */
  function openPower() {
    const wrap = $('#power-wrap'); wrap.classList.remove('hidden');
    const el = $('#power');
    el.innerHTML = `<h2>Power</h2><p>What would you like to do?</p><div class="pbtns">
      <button class="pbtn" data-a="logout"><span class="pc">${S.icon('logout')}</span>Log out</button>
      <button class="pbtn" data-a="reboot"><span class="pc">${S.icon('restart')}</span>Restart</button>
      <button class="pbtn" data-a="poweroff"><span class="pc">${S.icon('power')}</span>Shut down</button>
      <button class="pbtn" data-a="cancel"><span class="pc">${S.icon('close')}</span>Cancel</button></div>`;
    S.spring(el, { scale: .7, opacity: 0 }, { scale: 1, opacity: 1 }, { damping: .5 });
    S.$$('.pbtn', el).forEach((b, i) => S.spring(b, { y: 30, opacity: 0 }, { y: 0, opacity: 1 }, { delay: 60 + i * 50 }));
    el.onclick = e => {
      const b = e.target.closest('.pbtn'); if (!b) return;
      if (b.dataset.a === 'cancel') { close(); return; }
      S.boing(b.querySelector('.pc'), .2);
      setTimeout(() => S.send('session.action', { action: b.dataset.a }), 350);
    };
  }
  $('#power-wrap').addEventListener('click', e => { if (e.target === $('#power-wrap')) close(); });

  /* ================================================================ Welcome (first boot) */
  let wStep = 0;
  function openWelcome() {
    $('#welcome-wrap').classList.remove('hidden'); wStep = 0; renderWelcome(true);
  }
  async function renderWelcome(first) {
    const el = $('#welcome'); const name = (S.settings.user && S.settings.user.name) || 'friend';
    const steps = [
      () => `<img class="logo" src="${S.ctx.web}/icons/jstarx.svg" alt=""><h1>Welcome to JStarx, ${S.esc(name)}!</h1>
             <p>Your Jetson is ready. Let's set up three things. It takes about a minute.</p><button class="btn primary" data-next>Let's go</button>`,
      () => `<h1>Connect to Wi-Fi</h1><p>Pick your network. You can skip this if you use a cable.</p><div class="wifi-list scroll" id="w-wifi"><div class="faint">Looking for networks…</div></div>
             <div class="row" style="justify-content:center;margin-top:18px"><button class="btn" data-next>Skip</button><button class="btn primary" data-next>Next</button></div>`,
      () => `<h1>Pick your look</h1><p>Choose a wallpaper. You can change it later in Settings.</p><div class="walls">${['nebula', 'aurora', 'midnight', 'sunset'].map(w =>
               `<button data-wall="${w}" class="${S.settings.appearance.wallpaper === w ? 'on' : ''}"><img src="${S.ctx.assets}/wallpapers/${w}-thumb.jpg" alt="${w}"></button>`).join('')}</div>
             <div class="row" style="justify-content:center;margin-top:20px"><button class="btn primary" data-next>Next</button></div>`,
      () => `<img class="logo" style="width:84px;height:84px" src="${S.ctx.web}/icons/spark.svg" alt=""><h1>Meet Spark 1</h1><p>Spark is your built-in assistant. It needs its model file (about 1.2 GB). JStarx can download it from your GitHub release now.</p>
             <div class="row" style="justify-content:center"><button class="btn" data-next>Later</button><button class="btn primary" id="w-spark">${S.icon('download')} Download Spark 1</button></div>`,
      () => `<img class="logo" src="${S.ctx.web}/icons/jstarx.svg" alt=""><h1>You're all set!</h1><p>Tip: press the ★ in the dock for Start, or the grid for Launchpad. Click the island at the top for Control Center.</p><button class="btn primary" id="w-done">Start using JStarx</button>`,
    ];
    el.innerHTML = steps[wStep]() + `<div class="wsteps">${steps.map((_, i) => `<i class="${i === wStep ? 'on' : ''}"></i>`).join('')}</div>`;
    S.spring(el, first ? { scale: .6, opacity: 0 } : { x: 60, opacity: 0 }, { x: 0, scale: 1, opacity: 1 }, { damping: .55 });
    const logo = $('.logo', el); if (logo) S.spring(logo, { y: -40, scale: .4 }, { y: 0, scale: 1 }, { damping: .35, delay: 120 });
    S.$$('[data-next]', el).forEach(b => b.addEventListener('click', () => { wStep++; renderWelcome(); }));
    S.$$('[data-wall]', el).forEach(b => b.addEventListener('click', async () => {
      S.$$('[data-wall]', el).forEach(x => x.classList.toggle('on', x === b));
      try { S.applySettings(await S.call('settings.set', { path: 'appearance.wallpaper', value: b.dataset.wall })); } catch (e) { }
    }));
    if ($('#w-wifi')) loadWifi();
    if ($('#w-spark')) $('#w-spark').addEventListener('click', async () => {
      try { await S.call('spark.download'); S.toast('Spark 1 is downloading. The island will tell you when it is ready.'); } catch (e) { S.toast(e.message); }
      wStep++; renderWelcome();
    });
    if ($('#w-done')) $('#w-done').addEventListener('click', async () => {
      try { await S.call('settings.set', { path: 'welcome_done', value: true }); } catch (e) { }
      close();
    });
  }
  async function loadWifi() {
    let nets = []; try { nets = await S.call('net.wifi_list', { rescan: true }); } catch (e) { }
    const box = $('#w-wifi'); if (!box) return;
    box.innerHTML = nets.map(n => `<div class="wifi-row">${S.icon('wifi')}<b class="grow">${S.esc(n.ssid)}</b>${n.active ? '<span class="chip good">Connected</span>' :
      `${n.secure ? `<input class="field" type="password" placeholder="Password" style="height:34px;width:150px" data-pw="${S.esc(n.ssid)}">` : ''}<button class="btn small" data-join="${S.esc(n.ssid)}">Join</button>`}</div>`).join('') ||
      '<div class="faint">No Wi-Fi networks found. Is a Wi-Fi adapter plugged in?</div>';
    box.onclick = async e => {
      const b = e.target.closest('[data-join]'); if (!b) return;
      const pw = box.querySelector(`[data-pw="${CSS.escape(b.dataset.join)}"]`);
      b.textContent = 'Joining…';
      const r = await S.call('net.wifi_connect', { ssid: b.dataset.join, password: pw ? pw.value : null }).catch(e => ({ ok: false, message: e.message }));
      S.toast(r.ok ? 'Connected!' : 'Could not connect: ' + (r.message || ''));
      loadWifi();
    };
  }

  S.on('apps', () => { if (current === 'launchpad') renderLaunchpad(); });
  (async function init() { await Shell.loadApps(); S.send('shell.ready'); })();
})();
