/* Tiny shared engine for the JStarx games: loop, input (keys + gamepad), particles, best scores. */
(function () {
  'use strict';
  const S = window.StarX;
  const Game = {
    cv: null, ctx: null, w: 0, h: 0, running: false, paused: false, last: 0, shake: 0, parts: [],
    keys: new Set(), pressed: new Set(), best: 0, id: '',

    init(id, update, draw) {
      this.id = id; this.update = update; this.draw = draw;
      this.cv = document.getElementById('game'); this.ctx = this.cv.getContext('2d');
      const fit = () => { const r = this.cv.getBoundingClientRect(); this.cv.width = r.width * devicePixelRatio; this.cv.height = r.height * devicePixelRatio;
        this.w = r.width; this.h = r.height; this.ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0); };
      new ResizeObserver(fit).observe(this.cv); fit();
      addEventListener('keydown', e => { if (!this.keys.has(e.code)) this.pressed.add(e.code); this.keys.add(e.code); if (['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.code)) e.preventDefault(); });
      addEventListener('keyup', e => this.keys.delete(e.code));
      // power: pause when the window is hidden or loses focus
      document.addEventListener('visibilitychange', () => { if (document.hidden && this.running) this.pause(true); });
      addEventListener('blur', () => { if (this.running) this.pause(true); });
      S.call('appdata.get', { key: 'best' }).then(b => { this.best = b || 0; this.showBest(); }).catch(() => { });
    },
    showBest() { const el = document.getElementById('best'); if (el) el.textContent = this.best; },
    saveBest(score) {
      if (score > this.best) { this.best = score; this.showBest(); S.call('appdata.set', { key: 'best', value: score }).catch(() => { }); return true; }
      return false;
    },
    start() { this.running = true; this.paused = false; this.hide(); this.last = performance.now(); requestAnimationFrame(t => this.frame(t)); },
    stop() { this.running = false; },
    pause(on) {
      if (!this.running) return;
      this.paused = on;
      if (on) this.screen('Paused', 'Press P or click to continue');
      else { this.hide(); this.last = performance.now(); requestAnimationFrame(t => this.frame(t)); }
    },
    frame(t) {
      if (!this.running || this.paused) return;
      const dt = Math.min(0.05, (t - this.last) / 1000); this.last = t;
      this.pollPad();
      this.update(dt);
      this.parts = this.parts.filter(p => (p.life -= dt) > 0);
      this.parts.forEach(p => { p.x += p.vx * dt; p.y += p.vy * dt; p.vy += (p.g || 0) * dt; });
      const c = this.ctx;
      c.save();
      if (this.shake > 0) { c.translate((Math.random() - .5) * this.shake, (Math.random() - .5) * this.shake); this.shake = Math.max(0, this.shake - 60 * dt); }
      this.draw(c, dt);
      this.parts.forEach(p => { c.globalAlpha = Math.max(0, p.life / p.max); c.fillStyle = p.color; c.beginPath(); c.arc(p.x, p.y, p.r, 0, 6.283); c.fill(); });
      c.globalAlpha = 1; c.restore();
      this.pressed.clear();
      requestAnimationFrame(tt => this.frame(tt));
    },
    burst(x, y, color, n = 18, speed = 220) {
      for (let i = 0; i < n; i++) { const a = Math.random() * 6.283, s = speed * (.3 + Math.random());
        this.parts.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, r: 1.5 + Math.random() * 3, life: .5 + Math.random() * .5, max: 1, color, g: 300 }); }
    },
    pad: { left: false, right: false, up: false, down: false, a: false, start: false },
    pollPad() {
      const gp = navigator.getGamepads ? Array.from(navigator.getGamepads()).find(Boolean) : null;
      if (!gp) return;
      const ax = gp.axes[0] || 0, ay = gp.axes[1] || 0, b = i => gp.buttons[i] && gp.buttons[i].pressed;
      const prevA = this.pad.a, prevStart = this.pad.start;
      this.pad = { left: ax < -.4 || b(14), right: ax > .4 || b(15), up: ay < -.4 || b(12), down: ay > .4 || b(13), a: b(0), start: b(9) };
      if (this.pad.a && !prevA) this.pressed.add('Space');
      if (this.pad.start && !prevStart) this.pressed.add('KeyP');
    },
    left() { return this.keys.has('ArrowLeft') || this.keys.has('KeyA') || this.pad.left; },
    right() { return this.keys.has('ArrowRight') || this.keys.has('KeyD') || this.pad.right; },
    up() { return this.keys.has('ArrowUp') || this.keys.has('KeyW') || this.pad.up; },
    down() { return this.keys.has('ArrowDown') || this.keys.has('KeyS') || this.pad.down; },
    screen(title, sub, extra = '') {
      const o = document.getElementById('overlay');
      o.innerHTML = `<div class="card-o glass strong fixed-bg"><h1>${title}</h1><p>${sub}</p>${extra}</div>`;
      o.classList.remove('hidden');
      S.spring(o.firstElementChild, { scale: .7, opacity: 0, y: 30 }, { scale: 1, opacity: 1, y: 0 }, { damping: .5 });
    },
    hide() { document.getElementById('overlay').classList.add('hidden'); },
    star(c, x, y, r, color, rot = 0) {
      c.save(); c.translate(x, y); c.rotate(rot); c.fillStyle = color; c.beginPath();
      for (let i = 0; i < 8; i++) { const rr = i % 2 ? r * .38 : r; const a = i * Math.PI / 4 - Math.PI / 2; c.lineTo(Math.cos(a) * rr, Math.sin(a) * rr); }
      c.closePath(); c.fill(); c.restore();
    },
    roundRect(c, x, y, w, h, r) { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); },
  };
  window.Game = Game;
})();
