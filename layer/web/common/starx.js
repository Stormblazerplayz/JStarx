/* StarX web runtime: bridge to the Python host, events, spring animations, icons, helpers.
   Loaded by every shell surface and JStarx app. */
(function () {
  'use strict';
  const pending = new Map();
  const listeners = {};
  let seq = 0;
  const handler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.starx;

  const StarX = {
    ctx: window.STARX_CONTEXT || {},
    settings: {},

    /** Call a Python method. Returns a Promise with its result. */
    call(method, args = {}) {
      return new Promise((resolve, reject) => {
        if (!handler) { reject(new Error('StarX bridge not available')); return; }
        const id = ++seq;
        pending.set(id, { resolve, reject });
        handler.postMessage(JSON.stringify({ id, method, args }));
      });
    },
    /** Call without waiting for an answer. */
    send(method, args = {}) { this.call(method, args).catch(e => console.warn(method, e.message)); },
    on(name, fn) { (listeners[name] = listeners[name] || []).push(fn); return () => { listeners[name] = listeners[name].filter(f => f !== fn); }; },
    emit(name, data) {
      (listeners[name] || []).forEach(f => { try { f(data); } catch (e) { console.error(name, e); } });
      (listeners['*'] || []).forEach(f => { try { f(name, data); } catch (e) { console.error(e); } });
    },
    __resolve(id, ok, payload) {
      const p = pending.get(id); if (!p) return; pending.delete(id);
      ok ? p.resolve(payload) : p.reject(new Error(payload));
    },
    __event(name, data) { this.emit(name, data); },
  };

  /* ---------------- settings -> look ---------------- */
  StarX.applySettings = function (s) {
    if (!s) return;
    StarX.settings = s;
    const a = s.appearance || {};
    const root = document.documentElement;
    root.dataset.glass = a.glass || 'high';
    root.dataset.motion = a.motion || 'full';
    root.dataset.accent = a.accent || 'mix';
    root.dataset.bounce = String(a.bounce == null ? 0.6 : a.bounce);
    const wp = (StarX.ctx.assets || '') + '/wallpapers/' + (a.wallpaper || 'nebula');
    root.style.setProperty('--wall', `url("${wp}.jpg")`);
    root.style.setProperty('--wall-blur', `url("${wp}-blur.jpg")`);
    StarX.emit('settings', s);
  };
  StarX.on('settings-changed', s => StarX.applySettings(s));

  /* Align the blurred wallpaper inside a glass element with the real wallpaper on screen.
     ox/oy = where this web view sits on the screen. */
  StarX.alignGlass = function (el, ox = 0, oy = 0) {
    const sw = StarX.ctx.screen ? StarX.ctx.screen.width : window.innerWidth;
    const sh = StarX.ctx.screen ? StarX.ctx.screen.height : window.innerHeight;
    const r = el.getBoundingClientRect();
    // wallpaper is "cover"-fitted to the screen: 16:9 source
    const scale = Math.max(sw / 2560, sh / 1440);
    const w = 2560 * scale, h = 1440 * scale;
    const offX = (sw - w) / 2, offY = (sh - h) / 2;
    el.style.setProperty('--wall-size', `${w}px ${h}px`);
    el.style.setProperty('--wall-pos', `${offX - (ox + r.left)}px ${offY - (oy + r.top)}px`);
  };

  /** Paint the sharp wallpaper behind an opaque surface that sits at screen offset (ox, oy). */
  StarX.wallBehind = function (ox = 0, oy = 0) {
    const sw = StarX.ctx.screen ? StarX.ctx.screen.width : window.innerWidth;
    const sh = StarX.ctx.screen ? StarX.ctx.screen.height : window.innerHeight;
    const scale = Math.max(sw / 2560, sh / 1440);
    const w = 2560 * scale, h = 1440 * scale;
    document.body.classList.add('wall-behind');
    document.body.style.setProperty('--wall-size-body', `${w}px ${h}px`);
    document.body.style.setProperty('--wall-pos-body', `${(sw - w) / 2 - ox}px ${(sh - h) / 2 - oy}px`);
  };

  /* ---------------- spring animations (real bounce physics) ---------------- */
  function springCurve(zeta, w0) {
    const pts = []; const dt = 1 / 60;
    const pos = t => {
      if (zeta < 1) { const wd = w0 * Math.sqrt(1 - zeta * zeta); return 1 - Math.exp(-zeta * w0 * t) * (Math.cos(wd * t) + (zeta * w0 / wd) * Math.sin(wd * t)); }
      return 1 - Math.exp(-w0 * t) * (1 + w0 * t);
    };
    for (let t = 0; t < 2.5; t += dt) {
      const p = pos(t); pts.push(p);
      if (t > 0.15 && Math.abs(1 - p) < 0.0015 && Math.abs(pos(t + dt) - p) < 0.0008) break;
    }
    pts.push(1);
    return pts;
  }
  const lerp = (a, b, t) => a + (b - a) * t;
  function frame(from, to, p) {
    const v = k => lerp(from[k] ?? (k === 'scale' || k === 'sx' || k === 'sy' || k === 'opacity' ? 1 : 0), to[k] ?? (k === 'scale' || k === 'sx' || k === 'sy' || k === 'opacity' ? 1 : 0), p);
    const sx = (from.sx != null || to.sx != null) ? v('sx') : v('scale');
    const sy = (from.sy != null || to.sy != null) ? v('sy') : v('scale');
    const f = { transform: `translate(${v('x')}px, ${v('y')}px) scale(${sx}, ${sy}) rotate(${v('rotate')}deg)` };
    if (from.opacity != null || to.opacity != null) f.opacity = Math.max(0, Math.min(1, v('opacity')));
    if (from.radius != null || to.radius != null) f.borderRadius = `${v('radius')}px`;
    if (from.blur != null || to.blur != null) f.filter = `blur(${Math.max(0, v('blur'))}px)`;
    return f;
  }
  /** Animate el from state `from` to `to` ({x,y,scale,sx,sy,rotate,opacity,radius,blur}) with a spring. */
  StarX.spring = function (el, from, to, opts = {}) {
    const root = document.documentElement;
    const motion = root.dataset.motion || 'full';
    const bounce = parseFloat(root.dataset.bounce || '0.6');
    if (motion === 'off' || !el.animate) {
      const f = frame(from, to, 1); Object.assign(el.style, f); return Promise.resolve();
    }
    let zeta = opts.damping != null ? opts.damping : Math.max(0.32, 1 - 0.72 * bounce);
    if (motion === 'reduced') zeta = 1;
    const w0 = Math.sqrt((opts.stiffness || 300) / (opts.mass || 1));
    const curve = springCurve(zeta, w0);
    const keys = curve.map(p => frame(from, to, p));
    const anim = el.animate(keys, { duration: (curve.length / 60) * 1000 * (opts.speed || 1), delay: opts.delay || 0, easing: 'linear', fill: 'both' });
    return anim.finished.then(() => { if (opts.keep !== false) Object.assign(el.style, keys[keys.length - 1]); anim.cancel(); }).catch(() => {});
  };
  /** Little "boing" used when you press something. */
  StarX.boing = function (el, amount = 0.12) {
    return StarX.spring(el, { scale: 1 - amount }, { scale: 1 }, { stiffness: 420, keep: false });
  };
  /** Dock-style launch bounce (jumps a few times). */
  StarX.launchBounce = function (el, times = 3) {
    if ((document.documentElement.dataset.motion || 'full') !== 'full') return Promise.resolve();
    const keys = [];
    for (let i = 0; i < times; i++) {
      const h = 16 * Math.pow(0.7, i);
      keys.push({ transform: 'translateY(0) scale(1,1)', offset: i / times });
      keys.push({ transform: `translateY(${-h}px) scale(.96,1.05)`, offset: (i + 0.45) / times });
      keys.push({ transform: 'translateY(0) scale(1.06,.94)', offset: (i + 0.9) / times });
    }
    keys.push({ transform: 'translateY(0) scale(1,1)', offset: 1 });
    return el.animate(keys, { duration: 600 * times, easing: 'ease-in-out' }).finished.catch(() => {});
  };

  /* ---------------- icons (24px line icons) ---------------- */
  const P = {
    wifi: '<path d="M2.5 9a14 14 0 0 1 19 0"/><path d="M5.5 12.5a9.5 9.5 0 0 1 13 0"/><path d="M8.7 16a5 5 0 0 1 6.6 0"/><circle cx="12" cy="19.5" r="1.2" fill="currentColor"/>',
    wifiOff: '<path d="M3 3l18 18"/><path d="M8.7 16a5 5 0 0 1 6.6 0"/><path d="M5.5 12.5a9.5 9.5 0 0 1 4-2.3M15 10.6a9.5 9.5 0 0 1 3.5 1.9"/><circle cx="12" cy="19.5" r="1.2" fill="currentColor"/>',
    ethernet: '<rect x="3" y="7" width="18" height="11" rx="2"/><path d="M7 18v-3M11 18v-3M15 18v-3M8 7V4h8v3"/>',
    bluetooth: '<path d="M7 7l10 10-5 4V3l5 4L7 17"/>',
    volume: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
    mute: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.5 1.5M17.2 17.2l1.5 1.5M5.3 18.7l1.5-1.5M17.2 6.8l1.5-1.5"/>',
    moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>',
    bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    bellOff: '<path d="M3 3l18 18"/><path d="M8.5 5.6A6 6 0 0 1 18 11v4M6 11v5l-1.5 2H17"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    power: '<path d="M12 3v8"/><path d="M6.2 6.8a8 8 0 1 0 11.6 0"/>',
    restart: '<path d="M20 12a8 8 0 1 1-2.5-5.8"/><path d="M20 4v5h-5"/>',
    lock: '<rect x="5" y="10.5" width="14" height="10" rx="2.5"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
    logout: '<path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"/><path d="M10 16l-4-4 4-4M6 12h10"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/><circle cx="12" cy="12" r="6.8"/>',
    grid: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.8"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.8"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.8"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.8"/>',
    star: '<path d="M12 2.5c.9 5.6 3.9 8.6 9.5 9.5-5.6.9-8.6 3.9-9.5 9.5-.9-5.6-3.9-8.6-9.5-9.5 5.6-.9 8.6-3.9 9.5-9.5z" fill="currentColor" stroke="none"/>',
    bolt: '<path d="M13 2.5L5 13.5h6l-1 8 8-11h-6z"/>',
    leaf: '<path d="M5 19c0-9 5-14 15-15-1 10-6 15-15 15z"/><path d="M5 19l7-7"/>',
    gauge: '<path d="M4.5 17a8.5 8.5 0 1 1 15 0"/><path d="M12 13l4-4"/><circle cx="12" cy="13" r="1.3" fill="currentColor"/>',
    chip: '<rect x="6" y="6" width="12" height="12" rx="2.5"/><path d="M9.5 2.5v3.5M14.5 2.5v3.5M9.5 18v3.5M14.5 18v3.5M2.5 9.5H6M2.5 14.5H6M18 9.5h3.5M18 14.5h3.5"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2.5"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9.5 2.5v3.5M14.5 2.5v3.5M9.5 18v3.5M14.5 18v3.5M2.5 9.5H6M2.5 14.5H6M18 9.5h3.5M18 14.5h3.5"/>',
    memory: '<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M7 7v10M11 7v10M15 7v10M5 20v-3M19 20v-3"/>',
    disk: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    thermo: '<path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z"/><path d="M12 9v7"/>',
    fan: '<circle cx="12" cy="12" r="1.8"/><path d="M12 10.2c0-4 1-6.7 3.5-6.7 3 0 2.5 4.5-3.5 6.7zM13.8 12c4 0 6.7 1 6.7 3.5 0 3-4.5 2.5-6.7-3.5zM12 13.8c0 4-1 6.7-3.5 6.7-3 0-2.5-4.5 3.5-6.7zM10.2 12c-4 0-6.7-1-6.7-3.5 0-3 4.5-2.5 6.7 3.5z"/>',
    download: '<path d="M12 4v11M7 10.5l5 5 5-5"/><path d="M4.5 19.5h15"/>',
    upload: '<path d="M12 20V9M7 13.5l5-5 5 5"/><path d="M4.5 4.5h15"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 3.5V8h4.5"/><path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/><path d="M20 20.5V16h-4.5"/>',
    shield: '<path d="M12 3l7.5 3v6c0 4.5-3.2 7.8-7.5 9-4.3-1.2-7.5-4.5-7.5-9V6z"/><path d="M9 12l2.2 2.2L15.5 10"/>',
    wrench: '<path d="M14.5 4.5a4.5 4.5 0 0 0-5.3 5.9L3.8 15.8a1.8 1.8 0 0 0 2.6 2.6l5.4-5.4a4.5 4.5 0 0 0 5.9-5.3l-2.6 2.6-2.4-.4-.4-2.4z"/>',
    play: '<path d="M7.5 4.5v15l12-7.5z" fill="currentColor"/>',
    pause: '<rect x="6" y="4.5" width="4" height="15" rx="1.2" fill="currentColor" stroke="none"/><rect x="14" y="4.5" width="4" height="15" rx="1.2" fill="currentColor" stroke="none"/>',
    stop: '<rect x="5.5" y="5.5" width="13" height="13" rx="2.5" fill="currentColor" stroke="none"/>',
    trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    chevronR: '<path d="M9 5l7 7-7 7"/>',
    chevronL: '<path d="M15 5l-7 7 7 7"/>',
    chevronD: '<path d="M5 9l7 7 7-7"/>',
    folder: '<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    home: '<path d="M4 11l8-7 8 7v8.5a1.5 1.5 0 0 1-1.5 1.5H15v-6h-6v6H5.5A1.5 1.5 0 0 1 4 19.5z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>',
    display: '<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M8.5 20h7M12 16.5V20"/>',
    palette: '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.5 0 2-1.2 1.5-2.2-.6-1.1 0-2.3 1.4-2.3h2a4 4 0 0 0 3.6-4C20.5 7 16.7 3.5 12 3.5z"/><circle cx="7.8" cy="11" r="1.2" fill="currentColor"/><circle cx="10.5" cy="7.5" r="1.2" fill="currentColor"/><circle cx="15" cy="7.8" r="1.2" fill="currentColor"/>',
    dock: '<rect x="3" y="14.5" width="18" height="6" rx="3"/><path d="M7 17.5h.01M12 17.5h.01M17 17.5h.01" stroke-width="2.6"/><rect x="8" y="3.5" width="8" height="3.5" rx="1.75"/>',
    island: '<rect x="6" y="3.5" width="12" height="5" rx="2.5"/><rect x="3" y="11" width="18" height="9.5" rx="2.5"/>',
    apps: '<rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><path d="M17 13.5v7M13.5 17h7"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c-2.8 3-2.8 14 0 17M12 3.5c2.8 3 2.8 14 0 17"/>',
    info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><circle cx="12" cy="7.8" r="1" fill="currentColor"/>',
    bag: '<path d="M5.5 8h13l-1 12h-11z"/><path d="M9 8V6.5a3 3 0 0 1 6 0V8"/>',
    sparkle: '<path d="M12 3c.6 4.6 3.4 7.4 8 8-4.6.6-7.4 3.4-8 8-.6-4.6-3.4-7.4-8-8 4.6-.6 7.4-3.4 8-8z"/><path d="M19 3.5v3M17.5 5h3"/>',
    send: '<path d="M4 12l16-8-6 16-2.5-6.5z"/><path d="M11.5 13.5L20 4"/>',
    mic: '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"/>',
    terminal: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M7 9.5l3 2.5-3 2.5M12.5 15h4.5"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    eye: '<path d="M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    activity: '<path d="M3 12h4l2.5-6 5 12 2.5-6h4"/>',
    gamepad: '<path d="M7 8h10a4 4 0 0 1 4 4l.5 4a2.5 2.5 0 0 1-4.4 1.8L15.5 16h-7l-1.6 1.8A2.5 2.5 0 0 1 2.5 16L3 12a4 4 0 0 1 4-4z"/><path d="M7.5 11v3M6 12.5h3"/><circle cx="15.5" cy="11.5" r=".9" fill="currentColor"/><circle cx="17.5" cy="13.5" r=".9" fill="currentColor"/>',
    battery: '<rect x="3" y="7.5" width="16" height="9" rx="2"/><path d="M21 10.5v3"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7L11.5 6.8"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.5-1.5"/>',
    keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M9 10h.01M12 10h.01M15 10h.01M18 10h.01M7 14h10"/>',
    box: '<path d="M3.5 7.5L12 3l8.5 4.5v9L12 21l-8.5-4.5z"/><path d="M3.5 7.5L12 12l8.5-4.5M12 12v9"/>',
    rocket: '<path d="M12 3c3 2.5 4.5 6 4 10.5H8C7.5 9 9 5.5 12 3z"/><circle cx="12" cy="9" r="1.6"/><path d="M8 13.5l-2.5 3.5H9M16 13.5l2.5 3.5H15M10.5 17.5l1.5 3.5 1.5-3.5"/>',
  };
  StarX.icon = function (name, cls = 'ico') {
    const body = P[name] || P.star;
    return `<span class="${cls}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${body}</svg></span>`;
  };
  StarX.iconNames = Object.keys(P);

  /* ---------------- helpers ---------------- */
  StarX.esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  StarX.$ = (sel, root = document) => root.querySelector(sel);
  StarX.$$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  StarX.h = function (html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  StarX.bytes = function (n) {
    if (n == null || isNaN(n)) return '–';
    const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)) + ' ' + u[i];
  };
  StarX.duration = function (sec) {
    sec = Math.max(0, Math.round(sec || 0));
    const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
    if (d) return `${d}d ${h}h`; if (h) return `${h}h ${m}m`; if (m) return `${m}m`; return `${sec}s`;
  };
  StarX.time = function (date = new Date(), withSeconds = false) {
    const h24 = !(StarX.settings.clock && StarX.settings.clock.h24 === false);
    let h = date.getHours(); const m = String(date.getMinutes()).padStart(2, '0'); const s = String(date.getSeconds()).padStart(2, '0');
    let suffix = '';
    if (!h24) { suffix = h >= 12 ? ' PM' : ' AM'; h = h % 12 || 12; }
    return `${h24 ? String(h).padStart(2, '0') : h}:${m}${withSeconds ? ':' + s : ''}${suffix}`;
  };
  StarX.date = function (date = new Date()) {
    return date.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
  };
  StarX.toast = function (text, ms = 2600) {
    let host = document.querySelector('.toast-host');
    if (!host) { host = document.createElement('div'); host.className = 'toast-host'; document.body.appendChild(host); }
    const t = document.createElement('div'); t.className = 'toast'; t.textContent = text; host.appendChild(t);
    StarX.spring(t, { y: 24, scale: .9, opacity: 0 }, { y: 0, scale: 1, opacity: 1 });
    setTimeout(() => { StarX.spring(t, { opacity: 1, y: 0 }, { opacity: 0, y: 10 }, { damping: 1 }).then(() => t.remove()); }, ms);
  };
  /** Run fn once at the start of every minute (power friendly clocks). */
  StarX.everyMinute = function (fn) {
    fn();
    const schedule = () => setTimeout(() => { fn(); schedule(); }, 60000 - (Date.now() % 60000) + 50);
    schedule();
  };
  /** App icon URL for an app record from the registry. */
  StarX.appIcon = app => (app && app.icon) ? app.icon : (StarX.ctx.web + '/icons/jstarx-mark.svg');

  /* Full repaint. The first frames of a new surface can be lost before the window is on
     screen, so we repaint everything after load, after resizes and when a panel is shown. */
  StarX.repaint = function () {
    const r = document.documentElement;
    r.style.opacity = '0.999';
    requestAnimationFrame(() => requestAnimationFrame(() => { r.style.opacity = ''; }));
  };
  window.addEventListener('load', () => { [250, 900, 2200].forEach(t => setTimeout(StarX.repaint, t)); });
  let resizeT = null;
  window.addEventListener('resize', () => { clearTimeout(resizeT); resizeT = setTimeout(StarX.repaint, 60); });

  window.StarX = StarX;
  if (StarX.ctx.settings) StarX.applySettings(StarX.ctx.settings);
  document.addEventListener('contextmenu', e => { if (!e.target.closest('input,textarea,[data-allow-menu]')) e.preventDefault(); });
})();
