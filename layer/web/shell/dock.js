/* The bottom taskbar dock. */
(function () {
  'use strict';
  const S = window.StarX, $ = S.$;
  const dock = $('#dock');
  const surfH = () => cfg().size + 48;
  const launching = new Set();
  let hovering = false, menuOpen = false, hideTimer = null;

  function cfg() { return S.settings.dock || { size: 54, magnify: true, autohide: false, pinned: [] }; }

  function items() {
    const pinned = cfg().pinned.filter(id => Shell.byId[id]);
    const running = [];
    Shell.windows.forEach(w => {
      const app = Shell.apps.find(a => a.app_id === w.app_id);
      const id = app ? app.id : 'win:' + w.app_id;
      if (!pinned.includes(id) && !running.includes(id) && !(w.app_id || '').startsWith('starx-')) running.push(id);
    });
    return { pinned, running };
  }

  function appFor(id) {
    if (id.startsWith('win:')) { const aid = id.slice(4); return { id, name: aid, app_id: aid, icon: S.ctx.web + '/icons/globe.svg' }; }
    return Shell.byId[id];
  }

  function render() {
    const { pinned, running } = items();
    const btn = (id, extra = '') => {
      const a = appFor(id); if (!a) return '';
      const run = Shell.running(id) || (id.startsWith('win:'));
      return `<button class="di ${run ? 'running' : ''} ${extra}" data-id="${S.esc(id)}" aria-label="${S.esc(a.name)}">
        <img src="${S.esc(S.appIcon(a))}" alt=""><span class="dot"></span><span class="tip">${S.esc(a.name)}</span></button>`;
    };
    dock.innerHTML =
      `<button class="di start" data-sys="start" aria-label="Start"><img src="${S.ctx.web}/icons/jstarx.svg" alt=""><span class="tip">Start</span></button>` +
      `<button class="di" data-sys="launchpad" aria-label="Launchpad"><span class="sys">${S.icon('grid')}</span><span class="tip">Launchpad</span></button>` +
      `<span class="sep"></span>` + pinned.map(id => btn(id)).join('') +
      (running.length ? `<span class="sep"></span>` + running.map(id => btn(id)).join('') : '');
    dock.style.setProperty('--sz', cfg().size + 'px');
    S.$$('.di', dock).forEach(el => {
      el.addEventListener('click', () => onClick(el));
      el.addEventListener('contextmenu', e => { e.preventDefault(); onMenu(el); });
      el.addEventListener('pointerenter', () => { const t = el.getAttribute('aria-label'); if (t) S.send('shell.hint', { text: t }); });
      if (launching.has(el.dataset.id)) bounceLoop(el.dataset.id);
    });
    requestAnimationFrame(() => { sizeSurface(); alignGlass(); });
  }

  /* glass shows the blurred wallpaper exactly behind the dock */
  let geo = null;
  function alignGlass() {
    const scr = S.ctx.screen || { width: innerWidth, height: innerHeight };
    const ox = geo ? geo.x : (scr.width - innerWidth) / 2, oy = geo ? geo.y : scr.height - innerHeight;
    S.wallBehind(ox, oy);
    S.alignGlass(dock, ox, oy);
  }
  S.on('geometry', g => { geo = g; alignGlass(); S.repaint(); });
  window.addEventListener('resize', alignGlass);

  function sizeSurface() {
    const r = dock.getBoundingClientRect();
    const w = Math.ceil(r.width * (cfg().magnify ? 1.45 : 1.05) + 60);
    S.send('shell.size', { surface: 'dock', w: Math.min(w, (S.ctx.screen || {}).width || w), h: menuOpen ? surfH() + 220 : surfH(),
      exclusive: cfg().autohide ? 0 : surfH() });
  }

  function setInput() {
    const r = dock.getBoundingClientRect();
    if (menuOpen) { S.send('shell.input', { surface: 'dock', rects: null }); return; }
    return; /* opaque surface: the whole dock surface takes input */
    if (cfg().autohide && dock.classList.contains('hidden-away')) {
      S.send('shell.input', { surface: 'dock', rects: [{ x: 0, y: window.innerHeight - 6, w: window.innerWidth, h: 6 }] });
      return;
    }
    const pad = hovering && cfg().magnify ? cfg().size * 0.6 : 0;
    S.send('shell.input', { surface: 'dock', rects: [{ x: r.left - pad, y: r.top - pad - 4, w: r.width + 2 * pad, h: r.height + pad + 14 }] });
  }

  async function onClick(el) {
    const sys = el.dataset.sys;
    if (sys) { S.boing(el, .16); S.send('shell.open', { panel: sys }); return; }
    const id = el.dataset.id;
    if (id.startsWith('win:')) { S.send('windows.focus', { app_id: id.slice(4) }); S.boing(el); return; }
    if (!Shell.running(id)) { launching.add(id); bounceLoop(id); }
    else S.boing(el);
    await Shell.launch(id);
  }

  function bounceLoop(id) {
    const el = dock.querySelector(`.di[data-id="${CSS.escape(id)}"] img`);
    if (!el || el._bouncing) return;
    el._bouncing = true;
    const go = () => {
      if (!launching.has(id)) { el._bouncing = false; return; }
      S.launchBounce(el, 1).then(go);
    };
    go();
  }

  function onMenu(el) {
    const id = el.dataset.id; if (!id) return;
    const a = appFor(id); if (!a) return;
    const pinned = cfg().pinned.includes(id);
    const run = Shell.running(id) || id.startsWith('win:');
    menuOpen = true; sizeSurface();
    setTimeout(() => {
      const r = el.getBoundingClientRect();
      const m = Shell.menu(r.left - 60, r.top - 10, [
        { label: run ? `Show ${a.name}` : `Open ${a.name}`, icon: 'apps', action: () => onClick(el) },
        id.startsWith('win:') ? null : { label: pinned ? 'Remove from Dock' : 'Keep in Dock', icon: pinned ? 'minus' : 'plus', action: () => togglePin(id) },
        run ? { label: 'Quit', icon: 'close', action: () => S.send('windows.close', { app_id: a.app_id }) } : null,
      ].filter(Boolean));
      const mr = m.getBoundingClientRect();
      m.style.top = Math.max(4, r.top - mr.height - 12) + 'px';
      const obs = new MutationObserver(() => { if (!document.body.contains(m)) { obs.disconnect(); menuOpen = false; sizeSurface(); } });
      obs.observe(document.body, { childList: true });
    }, 60);
  }

  async function togglePin(id) {
    const list = cfg().pinned.slice();
    const i = list.indexOf(id);
    if (i >= 0) list.splice(i, 1); else list.push(id);
    try { S.applySettings(await S.call('settings.set', { path: 'dock.pinned', value: list })); } catch (e) { S.toast(e.message); }
    render();
  }

  /* magnification */
  dock.addEventListener('pointermove', e => {
    if (!cfg().magnify) return;
    if (!hovering) { hovering = true; dock.classList.remove('settle'); }
    const sz = cfg().size;
    S.$$('.di', dock).forEach(el => {
      const r = el.getBoundingClientRect();
      const d = Math.abs(e.clientX - (r.left + r.width / 2));
      const s = 1 + 0.3 * Math.max(0, 1 - d / (sz * 2.4));
      el.style.transform = `scale(${s})`;
      el.style.width = sz * (1 + (s - 1) * 0.55) + 'px';
    });
  });
  dock.addEventListener('pointerleave', () => {
    hovering = false; dock.classList.add('settle');
    S.$$('.di', dock).forEach(el => { el.style.transform = ''; el.style.width = ''; });
    S.send('shell.hint', { text: null });
    if (cfg().autohide) { clearTimeout(hideTimer); hideTimer = setTimeout(() => { dock.classList.add('hidden-away'); setInput(); }, 1200); }
  });
  dock.addEventListener('pointerenter', () => { clearTimeout(hideTimer); dock.classList.remove('hidden-away'); });
  document.body.addEventListener('pointerenter', () => { if (cfg().autohide) { dock.classList.remove('hidden-away'); setInput(); } });

  S.on('apps', render);
  S.on('windows', render);
  S.on('settings', () => { render(); if (!cfg().autohide) dock.classList.remove('hidden-away'); });
  S.on('launched', id => { launching.delete(id); });
  S.on('overlay-state', st => S.$$('.di[data-sys]', dock).forEach(b => b.classList.toggle('running', st.panel === b.dataset.sys)));

  S.on('dim', d => document.body.classList.toggle('dimmed', !!d.on));

  (async function init() {
    await Shell.loadApps();
    try { Shell.windows = await S.call('windows.list'); } catch (e) { }
    render();
    S.spring(dock, { y: 120, opacity: 0 }, { y: 0, opacity: 1 }, { damping: .55, delay: 200 }).then(() => { dock.style.transform = ''; });
    S.send('shell.ready');
  })();
})();
