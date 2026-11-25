/* Shared by all shell surfaces: the app list, launching, icon tiles. */
(function () {
  'use strict';
  const S = window.StarX;
  const Shell = {
    apps: [], byId: {}, windows: [], status: {},

    async loadApps() {
      try { this.apps = await S.call('apps.list'); } catch (e) { this.apps = []; }
      this.byId = Object.fromEntries(this.apps.map(a => [a.id, a]));
      S.emit('apps', this.apps);
      return this.apps;
    },
    running(appId) {
      const a = this.byId[appId];
      return !!a && this.windows.some(w => w.app_id === a.app_id);
    },
    async launch(id, el) {
      if (el) { S.boing(el.querySelector('.icon') || el, .14); }
      try { await S.call('apps.launch', { id }); }
      catch (e) { S.toast(e.message); }
    },
    tile(app, opts = {}) {
      if (!app) return '';
      return `<button class="app" data-app="${S.esc(app.id)}" title="${S.esc(app.description || app.name)}">
        <span class="icon"><img src="${S.esc(S.appIcon(app))}" alt=""></span>
        ${opts.noLabel ? '' : `<span class="label">${S.esc(app.name)}</span>`}
        ${opts.remove ? `<span class="remove-dot" data-remove="${S.esc(app.id)}">${S.icon('close')}</span>` : ''}
      </button>`;
    },
    folderTile(folder) {
      const list = folder.apps.map(id => this.byId[id]).filter(Boolean);
      const minis = list.slice(0, list.length > 4 ? 3 : 4).map(a => `<img src="${S.esc(S.appIcon(a))}" alt="">`).join('');
      const more = list.length > 4 ? `<span class="more">+${list.length - 3}</span>` : '';
      return `<button class="app folder" data-folder="${S.esc(folder.id)}" title="${S.esc(folder.name)}">
        <span class="icon">${minis}${more}</span><span class="label">${S.esc(folder.name)}</span></button>`;
    },
    /** FLIP: animate an element from a source rect to where it is now (with bounce). */
    morphFrom(el, fromRect, opts = {}) {
      const to = el.getBoundingClientRect();
      if (!fromRect || !to.width) return S.spring(el, { scale: .85, opacity: 0 }, { scale: 1, opacity: 1 }, opts);
      const sx = fromRect.width / to.width, sy = fromRect.height / to.height;
      const x = (fromRect.left + fromRect.width / 2) - (to.left + to.width / 2);
      const y = (fromRect.top + fromRect.height / 2) - (to.top + to.height / 2);
      el.style.transformOrigin = 'center center';
      return S.spring(el, { x, y, sx, sy, opacity: 0.2 }, { x: 0, y: 0, sx: 1, sy: 1, opacity: 1 }, opts);
    },
    morphTo(el, toRect, opts = {}) {
      const from = el.getBoundingClientRect();
      if (!toRect || !from.width) return S.spring(el, { opacity: 1, scale: 1 }, { opacity: 0, scale: .9 }, { damping: 1, ...opts });
      const sx = toRect.width / from.width, sy = toRect.height / from.height;
      const x = (toRect.left + toRect.width / 2) - (from.left + from.width / 2);
      const y = (toRect.top + toRect.height / 2) - (from.top + from.height / 2);
      return S.spring(el, { x: 0, y: 0, sx: 1, sy: 1, opacity: 1 }, { x, y, sx, sy, opacity: 0 }, { damping: .9, stiffness: 420, ...opts });
    },
    menu(x, y, items) {
      document.querySelectorAll('.menu').forEach(m => m.remove());
      const m = S.h(`<div class="menu glass strong fixed-bg">${items.map((it, i) => it === '-' ? '<hr>' :
        `<button data-i="${i}">${it.icon ? S.icon(it.icon) : ''}${S.esc(it.label)}</button>`).join('')}</div>`);
      document.body.appendChild(m);
      const r = m.getBoundingClientRect();
      m.style.left = Math.min(x, window.innerWidth - r.width - 8) + 'px';
      m.style.top = Math.min(y, window.innerHeight - r.height - 8) + 'px';
      S.spring(m, { scale: .85, opacity: 0, y: -6 }, { scale: 1, opacity: 1, y: 0 });
      const close = () => { m.remove(); document.removeEventListener('pointerdown', outside, true); };
      const outside = e => { if (!m.contains(e.target)) close(); };
      setTimeout(() => document.addEventListener('pointerdown', outside, true), 0);
      m.addEventListener('click', e => {
        const b = e.target.closest('button[data-i]'); if (!b) return;
        close(); const it = items[+b.dataset.i]; it.action && it.action();
      });
      return m;
    },
  };
  S.on('windows', w => { Shell.windows = w || []; });
  S.on('apps-changed', () => Shell.loadApps());
  S.on('status', st => { Object.assign(Shell.status, st); });
  window.Shell = Shell;
})();
