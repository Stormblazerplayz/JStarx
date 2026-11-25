/* Home screen: widgets + app folders, folder popups, edit mode. */
(function () {
  'use strict';
  const S = window.StarX, $ = S.$;
  let home = { items: [] };
  let editing = false;
  let openFolderId = null;
  let idle = false;

  /* ---------------- data ---------------- */
  async function loadHome() {
    try { home = await S.call('home.get'); } catch (e) { home = { items: [] }; }
  }
  function saveHome() { S.send('home.set', { layout: home }); }
  const folderById = id => home.items.find(i => i.type === 'folder' && i.id === id);

  /* ---------------- render grid ---------------- */
  function renderGrid() {
    const grid = $('#grid');
    const items = home.items.map(it => it.type === 'folder' ? Shell.folderTile(it) : Shell.tile(Shell.byId[it.id])).join('');
    grid.innerHTML = items;
    grid.style.setProperty('--cols', Math.min(4, Math.max(2, home.items.length)));
    grid.classList.toggle('editing', editing);
    S.$$('.app', grid).forEach((el, i) => {
      el.addEventListener('click', () => onTileClick(el));
      el.addEventListener('pointerdown', e => onTilePointer(e, el));
    });
  }
  function popIn() {
    S.$$('#grid .app').forEach((el, i) => S.spring(el, { scale: .6, opacity: 0, y: 30 }, { scale: 1, opacity: 1, y: 0 }, { delay: 60 * i }));
    S.$$('.widget').forEach((el, i) => S.spring(el, { x: -40, opacity: 0 }, { x: 0, opacity: 1 }, { delay: 80 * i, damping: .7 }));
  }

  function onTileClick(el) {
    if (el._dragged) { el._dragged = false; return; }
    if (el.dataset.folder) openFolder(el.dataset.folder, el);
    else if (!editing) Shell.launch(el.dataset.app, el);
  }

  /* ---------------- long press + drag to reorder ---------------- */
  function onTilePointer(e, el) {
    if (e.button !== 0) return;
    const start = { x: e.clientX, y: e.clientY };
    let ghost = null, timer = null, moved = false;
    if (!editing) {
      timer = setTimeout(() => { setEditing(true); }, 650);
    }
    const move = ev => {
      const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
      if (!moved && Math.hypot(dx, dy) > 8) { moved = true; clearTimeout(timer); if (editing) ghost = startGhost(el, ev); }
      if (ghost) {
        ghost.style.left = (ev.clientX - ghost._ox) + 'px'; ghost.style.top = (ev.clientY - ghost._oy) + 'px';
        S.$$('#grid .app').forEach(t => t.classList.toggle('drop-target', t !== el && hit(t, ev)));
      }
    };
    const up = ev => {
      clearTimeout(timer);
      document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', up);
      if (!ghost) return;
      el._dragged = true;
      const target = S.$$('#grid .app').find(t => t !== el && hit(t, ev));
      ghost.remove(); el.classList.remove('dragging');
      S.$$('.drop-target').forEach(t => t.classList.remove('drop-target'));
      if (target) {
        const tiles = S.$$('#grid .app');
        const from = tiles.indexOf(el), to = tiles.indexOf(target);
        const [moving] = home.items.splice(from, 1);
        if (moving.type === 'app' && target.dataset.folder) { folderById(target.dataset.folder).apps.push(moving.id); }
        else home.items.splice(to, 0, moving);
        saveHome(); renderGrid();
      }
    };
    document.addEventListener('pointermove', move); document.addEventListener('pointerup', up);
  }
  function hit(t, ev) { const r = t.getBoundingClientRect(); return ev.clientX > r.left && ev.clientX < r.right && ev.clientY > r.top && ev.clientY < r.bottom; }
  function startGhost(el, ev) {
    const r = el.getBoundingClientRect();
    const g = el.cloneNode(true); g.classList.add('ghost'); g.style.width = r.width + 'px';
    g._ox = ev.clientX - r.left; g._oy = ev.clientY - r.top;
    g.style.left = r.left + 'px'; g.style.top = r.top + 'px';
    document.body.appendChild(g); el.classList.add('dragging');
    return g;
  }

  function setEditing(on) {
    editing = on;
    $('#edit-bar').classList.toggle('hidden', !on);
    if (on) S.spring($('#edit-bar'), { y: -30, opacity: 0, scale: .9 }, { y: 0, opacity: 1, scale: 1 });
    renderGrid();
    if (openFolderId) renderFolder(openFolderId);
  }

  /* ---------------- folders ---------------- */
  let folderSource = null;
  function openFolder(id, fromEl) {
    openFolderId = id;
    folderSource = fromEl ? fromEl.querySelector('.icon').getBoundingClientRect() : null;
    const layer = $('#folder-layer');
    layer.classList.remove('hidden');
    S.send('shell.dim', { on: true });
    renderFolder(id);
    const panel = $('.fpanel', layer);
    Shell.morphFrom(panel, folderSource, { stiffness: 340 });
    S.spring($('.backdrop', layer), { opacity: 0 }, { opacity: 1 }, { damping: 1 });
    S.$$('.fgrid .app', layer).forEach((a, i) => S.spring(a, { scale: .5, opacity: 0 }, { scale: 1, opacity: 1 }, { delay: 90 + i * 35 }));
  }
  function renderFolder(id) {
    const f = folderById(id);
    const layer = $('#folder-layer');
    const old = $('.fpanel', layer); if (old) old.remove();
    if (!f) { closeFolder(true); return; }
    const panel = S.h(`<div class="fpanel glass fixed-bg">
      <h2>${editing ? `<input id="fname" value="${S.esc(f.name)}" maxlength="24">` : S.esc(f.name)}</h2>
      <div class="fgrid ${editing ? 'editing' : ''}">${f.apps.map(a => Shell.tile(Shell.byId[a], { remove: editing })).join('') ||
        '<div class="faint" style="grid-column:1/-1;padding:20px">This folder is empty.</div>'}</div>
      ${editing ? `<div class="tools"><button class="btn small" id="add-apps">${S.icon('plus')} Add apps</button>
        <button class="btn small danger" id="del-folder">${S.icon('trash')} Delete folder</button></div><div class="picker scroll hidden" id="picker"></div>` : ''}
    </div>`);
    $('.fcenter', layer).appendChild(panel);
    panel.addEventListener('click', e => {
      const rm = e.target.closest('[data-remove]');
      if (rm) { e.stopPropagation(); f.apps = f.apps.filter(x => x !== rm.dataset.remove); saveHome(); renderFolder(id); renderGrid(); return; }
      const tile = e.target.closest('.app[data-app]');
      if (tile && !editing && !tile.closest('#picker')) { Shell.launch(tile.dataset.app, tile); setTimeout(() => closeFolder(), 260); }
      if (tile && tile.closest('#picker')) { f.apps.push(tile.dataset.app); saveHome(); renderFolder(id); renderGrid(); }
    });
    const name = $('#fname', panel);
    if (name) name.addEventListener('change', () => { f.name = name.value.trim() || 'Folder'; saveHome(); renderGrid(); });
    const add = $('#add-apps', panel);
    if (add) add.addEventListener('click', () => {
      const picker = $('#picker', panel); picker.classList.toggle('hidden');
      const used = new Set(f.apps);
      picker.innerHTML = Shell.apps.filter(a => !used.has(a.id)).map(a => Shell.tile(a)).join('') || '<div class="faint">All apps are already here.</div>';
    });
    const del = $('#del-folder', panel);
    if (del) del.addEventListener('click', () => { home.items = home.items.filter(i => i !== f); saveHome(); closeFolder(); renderGrid(); });
  }
  function closeFolder(instant) {
    const layer = $('#folder-layer'); const panel = $('.fpanel', layer);
    openFolderId = null;
    S.send('shell.dim', { on: false });
    if (instant || !panel) { layer.classList.add('hidden'); return; }
    const tile = folderSource;
    S.spring($('.backdrop', layer), { opacity: 1 }, { opacity: 0 }, { damping: 1, stiffness: 500 });
    Shell.morphTo(panel, tile).then(() => { layer.classList.add('hidden'); panel.remove(); });
  }
  $('#folder-layer').addEventListener('click', e => { if (e.target.classList.contains('backdrop') || e.target.classList.contains('fcenter')) closeFolder(); });

  $('#new-folder').addEventListener('click', () => {
    const f = { type: 'folder', id: 'f' + Date.now().toString(36), name: 'New Folder', apps: [] };
    home.items.push(f); saveHome(); renderGrid(); openFolder(f.id, S.$(`[data-folder="${f.id}"]`));
  });
  $('#edit-done').addEventListener('click', () => setEditing(false));

  /* ---------------- widgets ---------------- */
  function tickClock() {
    const now = new Date(), h = now.getHours();
    $('#clock').textContent = S.time(now);
    $('#date').textContent = S.date(now);
    const name = (S.settings.user && S.settings.user.name) || '';
    const part = h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
    $('#greet').textContent = `${part}${name ? ', ' + name : ''}`;
  }
  function ring(label, pct, text, color) {
    const r = 29, c = 2 * Math.PI * r, off = c * (1 - Math.max(0, Math.min(1, pct / 100)));
    return `<div class="ring"><svg viewBox="0 0 70 70"><circle cx="35" cy="35" r="${r}" fill="none" stroke="rgba(255,255,255,.14)" stroke-width="7"/>
      <circle cx="35" cy="35" r="${r}" fill="none" stroke="${color}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${off}" style="transition:stroke-dashoffset .8s var(--ease)"/></svg>
      <span class="v">${text}</span>${label}</div>`;
  }
  async function refreshStats() {
    if (idle) return;
    try {
      const st = await S.call('system.stats');
      const mem = st.memory.total ? 100 * st.memory.used / st.memory.total : 0;
      $('#rings').innerHTML = ring('CPU', st.cpu, Math.round(st.cpu) + '%', '#FF8A00') + ring('Memory', mem, Math.round(mem) + '%', '#C77DFF') +
        ring('Temp', st.temp == null ? 0 : st.temp, st.temp == null ? '–' : Math.round(st.temp) + '°', '#FF9F43');
    } catch (e) { /* ignore */ }
  }
  function renderAiLine() {
    const ai = Shell.status.ai || {};
    const running = (ai.jobs || []).filter(j => j.state === 'running');
    $('#ai-line').innerHTML = S.icon('chip') + (running.length ? `${running.length} AI job${running.length > 1 ? 's' : ''} running` : 'No AI jobs running');
  }
  async function refreshSpark() {
    $('#spark-img').src = S.ctx.web + '/icons/spark.svg';
    let st = {};
    try { st = await S.call('spark.status'); } catch (e) { }
    const state = st.engine === 'ok' ? 'Ready to help' : (st.state === 'downloading' ? `Downloading model… ${st.progress || 0}%` :
      st.model ? 'Starting up…' : 'Waiting for the Spark 1 model');
    $('#spark-state').textContent = state;
  }
  $('#spark-form').addEventListener('submit', e => {
    e.preventDefault();
    const q = $('#spark-q').value.trim(); if (!q) return;
    $('#spark-q').value = '';
    S.send('shell.open', { panel: 'spark', data: { q } });
  });

  /* ---------------- desktop menu + keys ---------------- */
  document.addEventListener('contextmenu', e => {
    if (e.target.closest('input')) return;
    Shell.menu(e.clientX, e.clientY, [
      { label: editing ? 'Stop editing' : 'Edit home screen', icon: 'edit', action: () => setEditing(!editing) },
      { label: 'Open Launchpad', icon: 'grid', action: () => S.send('shell.open', { panel: 'launchpad' }) },
      '-',
      { label: 'Change wallpaper…', icon: 'palette', action: () => Shell.launch('settings') },
      { label: 'Settings', icon: 'settings', action: () => Shell.launch('settings') },
    ]);
  });
  document.addEventListener('keydown', e => {
    if (e.target.closest('input')) return;
    if (e.key === 'Escape') { if (openFolderId) closeFolder(); else if (editing) setEditing(false); return; }
    if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) S.send('shell.open', { panel: 'launchpad', data: { q: e.key } });
  });

  /* ---------------- events ---------------- */
  S.on('apps', () => { renderGrid(); if (openFolderId) renderFolder(openFolderId); });
  S.on('settings', () => { tickClock(); });
  S.on('status', st => { if (st.ai) renderAiLine(); if (st.spark) refreshSpark(); });
  S.on('idle', v => { idle = v; if (!v) refreshStats(); });

  (async function init() {
    await Promise.all([Shell.loadApps(), loadHome()]);
    try { Object.assign(Shell.status, (await S.call('shell.state')).status || {}); } catch (e) { }
    renderGrid(); popIn();
    S.everyMinute(tickClock);
    refreshStats(); setInterval(refreshStats, 10000);
    refreshSpark(); setInterval(refreshSpark, 30000);
    renderAiLine();
    S.send('shell.ready');
  })();
})();
