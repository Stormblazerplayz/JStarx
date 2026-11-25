/* JStarx Settings. Every page is built from small helpers; settings save instantly. */
(function () {
  'use strict';
  const S = window.StarX, $ = S.$, esc = S.esc;
  let current = 'wifi';

  /* ---------------- helpers ---------------- */
  const get = path => path.split('.').reduce((o, k) => (o == null ? o : o[k]), S.settings);
  const item = (t, s, ctl = '') => `<div class="item"><div class="txt"><div class="t">${t}</div>${s ? `<div class="s">${s}</div>` : ''}</div><div class="ctl">${ctl}</div></div>`;
  const toggle = (path, val) => `<button class="toggle" role="switch" aria-checked="${!!(val == null ? get(path) : val)}" data-toggle="${path}"></button>`;
  const slider = (path, min, max, step, unit = '') => `<input type="range" class="slider" min="${min}" max="${max}" step="${step}" value="${get(path)}" data-range="${path}" data-unit="${unit}"><span class="val">${get(path)}${unit}</span>`;
  const choice = (path, opts, n) => `<div class="choice" style="--n:${n || opts.length}">${opts.map(o =>
    `<button class="${get(path) === o.v ? 'on' : ''}" data-choice="${path}" data-v="${esc(o.v)}"><div class="ct">${o.icon ? S.icon(o.icon) : ''}${esc(o.t)}</div>${o.s ? `<div class="cs">${esc(o.s)}</div>` : ''}</button>`).join('')}</div>`;
  const card = (title, body, pad) => `<section class="card ${pad ? 'pad' : ''}">${title ? `<h2>${title}</h2>` : ''}${body}</section>`;
  const call = async (method, args, okText) => {
    try { const r = await S.call(method, args); if (okText) S.toast(okText); return r; }
    catch (e) { S.toast(e.message); return null; }
  };
  async function setSetting(path, value) {
    const s = await call('settings.set', { path, value });
    if (s) S.applySettings(s);
  }

  /* ---------------- pages ---------------- */
  const PAGES = [
    { id: 'wifi', name: 'Wi-Fi & Network', icon: 'wifi', color: 'blue', render: pageWifi, keys: 'internet network ethernet hostname' },
    { id: 'display', name: 'Display & Casting', icon: 'display', color: 'teal', render: pageDisplay, keys: 'screen resolution cast miracast chromecast tv wireless' },
    { id: 'appearance', name: 'Appearance', icon: 'palette', color: 'pink', render: pageAppearance, keys: 'wallpaper theme glass color accent animation bounce' },
    { id: 'dock', name: 'Dock & Island', icon: 'dock', color: 'purple', render: pageDock, keys: 'taskbar island notifications magnify autohide' },
    { id: 'home', name: 'Home & Launchpad', icon: 'home', color: 'orange', render: pageHome, keys: 'folders launchpad layout' },
    { id: 'sound', name: 'Sound', icon: 'volume', color: 'red', render: pageSound, keys: 'volume audio mute' },
    { id: 'power', name: 'Power', icon: 'bolt', color: 'green', render: pagePower, keys: 'battery saver performance screen sleep temperature 24/7' },
    { id: 'spark', name: 'AI & Spark', icon: 'sparkle', color: 'purple', render: pageSpark, keys: 'spark model assistant ai weights gguf' },
    { id: 'apps', name: 'Apps', icon: 'apps', color: 'orange', render: pageApps, keys: 'installed uninstall store' },
    { id: 'updates', name: 'Updates', icon: 'refresh', color: 'blue', render: pageUpdates, keys: 'update github version rollback' },
    { id: 'repair', name: 'Repair & Recovery', icon: 'shield', color: 'green', render: pageRepair, keys: 'fix broken reset recovery safe' },
    { id: 'memory', name: 'Memory', icon: 'memory', color: 'orange', render: pageMemory, keys: 'ram swap zram memory free 8gb 12gb' },
    { id: 'storage', name: 'Storage', icon: 'disk', color: 'gray', render: pageStorage, keys: 'disk space clean' },
    { id: 'users', name: 'Users & Privacy', icon: 'user', color: 'teal', render: pageUsers, keys: 'name login ssh password' },
    { id: 'time', name: 'Date & Time', icon: 'clock', color: 'gray', render: pageTime, keys: 'timezone clock 24' },
    { id: 'about', name: 'About JStarx', icon: 'info', color: 'purple', render: pageAbout, keys: 'version kernel hardware starx' },
  ];

  async function pageWifi() {
    const st = await call('net.status') || {};
    const wired = (st.devices || []).filter(d => d.type === 'ethernet');
    let html = card('', item('Wi-Fi', st.ssid ? `Connected to <b>${esc(st.ssid)}</b>${st.signal != null ? ` · ${st.signal}% signal` : ''}` : (st.wifi_on === false ? 'Off' : 'Not connected'),
      `<button class="toggle" role="switch" aria-checked="${st.wifi_on !== false}" id="wifi-radio"></button>`) +
      wired.map(d => item('Ethernet', d.state.startsWith('connected') ? `Connected (${esc(d.device)})` : 'Cable not plugged in', S.icon('ethernet'))).join(''));
    html += card('Networks', `<div id="nets"><div class="empty">Searching for networks…</div></div><div class="item"><div class="txt"></div><div class="ctl"><button class="btn small" id="rescan">${S.icon('refresh')} Scan again</button></div></div>`);
    setTimeout(() => loadNets(false), 0);
    return html;
  }
  async function loadNets(rescan) {
    const box = $('#nets'); if (!box) return;
    const nets = await call('net.wifi_list', { rescan }) || [];
    box.innerHTML = nets.length ? nets.map(n => `<div class="list-row">${S.icon('wifi')}<div class="grow"><b>${esc(n.ssid)}</b><div class="faint" style="font-size:12.5px">${n.signal}% · ${n.secure ? 'Secured' : 'Open'}</div></div>
      ${n.active ? '<span class="chip good">Connected</span>' : `${n.secure ? `<input class="field" type="password" placeholder="Password" data-pw="${esc(n.ssid)}" style="height:34px;width:170px">` : ''}<button class="btn small" data-join="${esc(n.ssid)}">Join</button>`}</div>`).join('')
      : '<div class="empty">No Wi-Fi networks found. Is a Wi-Fi adapter connected?</div>';
  }

  async function pageDisplay() {
    const d = await call('display.get') || { outputs: [] };
    const cast = d.cast_status || {};
    const castState = { casting: `Showing JStarx on <b>${esc(cast.device || '')}</b>`, searching: 'Looking for wireless displays…', 'none-found': 'No wireless displays found yet', 'screen-connected': 'A screen is plugged in, so auto-cast is resting', off: 'Off' }[cast.state] || 'Waiting';
    let html = card('Screens', (d.outputs || []).map(o => item(esc(o.name) + (o.description ? ` <span class="faint">${esc(o.description.slice(0, 40))}</span>` : ''), `Now ${esc(o.mode || 'unknown')} · scale ${o.scale}`,
      `<select class="field" data-output="${esc(o.name)}" data-kind="mode">${(o.modes || []).map(m => `<option ${o.mode && o.mode.startsWith(m) ? 'selected' : ''}>${m}</option>`).join('')}</select>
       <select class="field" data-output="${esc(o.name)}" data-kind="scale">${[1, 1.25, 1.5, 2].map(x => `<option ${x == o.scale ? 'selected' : ''}>${x}</option>`).join('')}</select>`)).join('') || '<div class="empty">No screen information available.</div>');
    html += card('Wireless display', item('Cast your screen', d.casting ? 'Send JStarx to a TV or display over Wi-Fi (Miracast or Chromecast).' : 'Casting is not installed on this system.',
      `<button class="btn primary small" id="cast-now" ${d.casting ? '' : 'disabled'}>${S.icon('display')} Cast now</button>`) +
      item('Auto-cast when no screen is plugged in', 'If the Jetson starts without a screen, JStarx finds a Chromecast or TV on your network and shows itself there.', toggle('cast.auto')) +
      item('Auto-cast status', castState, '') +
      item('Preferred display', 'Name of the TV to use first (leave empty for the first one found).', `<input class="field" id="cast-device" value="${esc(get('cast.device'))}" placeholder="Living Room TV" style="width:200px">`) +
      item('Cast quality', 'Higher quality uses more power.', `<select class="field" data-select="cast.resolution">${['854x480', '1280x720', '1920x1080'].map(r => `<option ${get('cast.resolution') === r ? 'selected' : ''}>${r}</option>`).join('')}</select>`) +
      item('Cast frame rate', 'Frames per second sent to the display.', slider('cast.fps', 5, 30, 1, ' fps')));
    return html;
  }

  async function pageAppearance() {
    const walls = ['nebula', 'aurora', 'midnight', 'sunset'];
    return card('Wallpaper', `<div class="thumbs">${walls.map(w => `<button class="${get('appearance.wallpaper') === w ? 'on' : ''}" data-choice="appearance.wallpaper" data-v="${w}"><img src="${S.ctx.assets}/wallpapers/${w}-thumb.jpg" alt=""><span>${w}</span></button>`).join('')}</div>`) +
      card('Accent', choice('appearance.accent', [{ v: 'mix', t: 'Purple + Orange', s: 'The JStarx look', icon: 'star' }, { v: 'purple', t: 'Purple', s: 'Calm and deep', icon: 'moon' }, { v: 'orange', t: 'Orange', s: 'Warm and bright', icon: 'sun' }])) +
      card('Liquid glass', choice('appearance.glass', [{ v: 'high', t: 'Crystal', s: 'Most see-through' }, { v: 'medium', t: 'Frosted', s: 'Balanced' }, { v: 'low', t: 'Smoky', s: 'Easier to read' }, { v: 'off', t: 'Solid', s: 'No transparency' }])) +
      card('Animations', choice('appearance.motion', [{ v: 'full', t: 'Full', s: 'Springs and bounces', icon: 'sparkle' }, { v: 'reduced', t: 'Reduced', s: 'Gentle, no bounce' }, { v: 'off', t: 'Off', s: 'Instant, saves power' }]) +
        item('Bounciness', 'How much things wobble when they spring into place.', slider('appearance.bounce', 0, 1, 0.05)) +
        `<div class="item"><div class="txt"><div class="t">Try it</div><div class="s">Watch the star bounce with your settings.</div></div><div class="ctl"><button class="btn small" id="try-bounce"><span id="bounce-star" style="display:inline-block">${S.icon('star')}</span> Bounce</button></div></div>`);
  }

  async function pageDock() {
    const apps = await call('apps.list') || [];
    const pinned = get('dock.pinned');
    return card('Dock', item('Icon size', '', slider('dock.size', 36, 80, 2, ' px')) + item('Magnify on hover', 'Icons grow as your pointer moves over them.', toggle('dock.magnify')) +
      item('Hide automatically', 'The dock slides away until you move to the bottom of the screen.', toggle('dock.autohide'))) +
      card('Apps in the dock', apps.map(a => `<div class="list-row"><img src="${esc(S.appIcon(a))}" width="34" height="34" style="border-radius:9px"><b class="grow">${esc(a.name)}</b>
        <button class="toggle" role="switch" aria-checked="${pinned.includes(a.id)}" data-pin="${esc(a.id)}"></button></div>`).join('')) +
      card('Dynamic island', item('Show seconds', '', toggle('island.seconds')) + item('Show AI activity', 'Training progress and temperature appear in the island.', toggle('island.ai_activity')) +
        item('Show notifications', 'App notifications pop out of the island.', toggle('island.notifications')) + item('Do Not Disturb', 'Hide notifications until you turn this off.', toggle('island.dnd')));
  }

  async function pageHome() {
    return card('Home screen', item('Edit home screen', 'Right-click the desktop or hold a folder to edit folders: rename, add apps, reorder.', '') +
      item('Reset home screen', 'Put the folders back the way JStarx started.', `<button class="btn small" id="reset-home">${S.icon('restart')} Reset</button>`)) +
      card('Launchpad', item('Columns', 'How many apps fit in one row.', slider('launchpad.columns', 4, 10, 1)) +
        item('Open Launchpad', 'Tip: start typing on the desktop to search.', `<button class="btn small" id="open-lp">${S.icon('grid')} Open</button>`));
  }

  async function pageSound() {
    const a = await call('audio.get') || {};
    if (!a.available) return card('', '<div class="empty">No sound output found. Plug in HDMI audio, a USB speaker or headphones.</div>');
    return card('Output', item('Volume', a.muted ? 'Muted' : '', `<input type="range" class="slider" id="vol" min="0" max="100" value="${a.volume}"><span class="val" id="vol-v">${a.volume}%</span>`) +
      item('Mute', '', `<button class="toggle" role="switch" aria-checked="${!!a.muted}" id="mute"></button>`));
  }

  async function pagePower() {
    const p = await call('power.get') || {};
    const st = await call('system.stats') || {};
    const prof = p.profile || 'balanced';
    const modes = [
      { v: 'low', t: 'Low power', s: '1 CPU core, lowest speed. Uses the least power and heat.', icon: 'leaf' },
      { v: 'saver', t: 'Power saver', s: '2 CPU cores, low speed. Cool and quiet.', icon: 'leaf' },
      { v: 'balanced', t: 'Balanced', s: 'All cores, speed adapts to the work. Best for most things.', icon: 'gauge' },
      { v: 'performance', t: 'Performance', s: 'All cores at full speed. For games and AI training.', icon: 'bolt' },
      { v: 'extreme', t: 'Extreme', s: 'Everything locked at full speed, fan at max. Fastest, hottest. Use a good power supply.', icon: 'bolt' }];
    return card('Power mode', `<div class="choice" style="--n:5">${modes.map(o => `<button class="${prof === o.v ? 'on' : ''}" data-power="1" data-v="${o.v}"><div class="ct">${S.icon(o.icon)}${o.t}</div><div class="cs">${o.s}</div></button>`).join('')}</div>`) +
      (p.has_fan !== false ? card('Fan', item('Fan speed', 'Auto: the fan speeds up when the Jetson gets warm. Max: always full speed (best for 24/7 AI). Extreme mode always uses Max.',
        `<button class="btn small ${p.fan !== 'max' ? 'primary' : ''}" data-fan="auto">Auto</button><button class="btn small ${p.fan === 'max' ? 'primary' : ''}" data-fan="max">Max</button>`)) : '') +
      card('24/7 AI mode', item('Keep AI running all the time', 'Never sleeps, restarts AI jobs after power cuts, turns the screen off when idle, and uses the watchdog so a freeze reboots the Jetson.',
        `<button class="toggle" role="switch" aria-checked="${!!p.ai_247}" id="ai247"></button>`)) +
      card('Screen', item('Dim the screen after', '0 = never', slider('power.dim_min', 0, 60, 1, ' min')) + item('Turn the screen off after', '0 = never', slider('power.screen_off_min', 0, 120, 1, ' min'))) +
      card('Temperatures', (st.temps || []).map(t => item(esc(t.name), '', `<span class="chip ${t.c > 80 ? 'bad' : t.c > 65 ? 'warn' : 'good'}">${t.c}°C</span>`)).join('') || '<div class="empty">No temperature sensors found.</div>') +
      (p.service === false ? '<p class="faint">Power modes need the JStarx system service (starxd).</p>' : '');
  }

  async function pageSpark() {
    const sp = await call('spark.status') || {};
    const ready = sp.engine === 'ok';
    const state = ready ? '<span class="chip good">Running</span>' : sp.state === 'downloading' ? `<span class="chip accent">Downloading ${sp.progress || 0}%</span>` :
      sp.state === 'converting' ? '<span class="chip accent">Converting</span>' : sp.state === 'needs-tokenizer' ? '<span class="chip warn">Needs tokenizer</span>' :
      sp.state === 'error' ? '<span class="chip bad">Problem</span>' : sp.model ? '<span class="chip warn">Starting</span>' : '<span class="chip warn">No model yet</span>';
    return `<div class="big-stat" style="--n:3"><div><span>Spark 1</span><b>${ready ? 'Ready' : 'Waiting'}</b></div><div><span>Model file</span><b style="font-size:16px;word-break:break-all">${esc(sp.model || '—')}</b></div><div><span>Size</span><b>${sp.size ? S.bytes(sp.size) : '—'}</b></div></div>` +
      card('Get the Spark 1 model', item('Status', esc(sp.message || 'Spark answers questions on this Jetson, with no internet needed once installed.'), state) +
        item('Download from GitHub release', 'The release your model is uploaded to (sft_best.pt + tokenizer.json). JStarx downloads every model file there and converts it.', `<input class="field" id="model-url" value="${esc(get('spark.model_url'))}" style="width:320px">`) +
        `<div class="item"><div class="txt"></div><div class="ctl"><button class="btn primary small" id="spark-dl">${S.icon('download')} Download Spark 1</button></div></div>` +
        item('Or use a file you already have', 'Full path to a .gguf or .pt model file, or its tokenizer.json (for example on a USB stick).', `<input class="field" id="model-path" placeholder="/run/media/storm/USB/sft_best.pt" style="width:320px"><button class="btn small" id="spark-import">Import</button>`)) +
      card('Engine', item('Spark engine', 'llama.cpp running on this Jetson (127.0.0.1:8090).', `<button class="btn small" data-spark="restart">${S.icon('restart')} Restart</button><button class="btn small" data-spark="stop">${S.icon('stop')} Stop</button>`) +
        item('Faster answers', 'Uses a smaller copy of Spark 1: about twice as fast on the Jetson, a little less smart. (The Jetson\'s GPU needs NVIDIA\'s own old kernel, so Spark runs on the 4 CPU cores.)', toggle('spark.fast')) +
        item('CPU threads', '', slider('spark.threads', 1, 8, 1)) + item('Memory (context length)', 'Longer means Spark remembers more of the chat but uses more RAM.', slider('spark.ctx', 512, 8192, 512, ' tokens'))) +
      card('Personality', `<div style="padding:12px 0"><textarea class="field" id="persona">${esc(get('spark.personality'))}</textarea><div style="margin-top:10px;text-align:right"><button class="btn small" id="persona-save">Save</button></div></div>`) +
      card('', item('AI Center', 'Run models and training jobs 24/7, watch temperatures and progress.', `<button class="btn small" id="open-ai">${S.icon('chip')} Open AI Center</button>`));
  }

  async function pageApps() {
    const apps = await call('apps.list') || [];
    const extra = apps.filter(a => !a.builtin);
    return card('Built in', apps.filter(a => a.builtin).map(a => `<div class="list-row"><img src="${esc(S.appIcon(a))}" width="34" height="34" style="border-radius:9px"><div class="grow"><b>${esc(a.name)}</b><div class="faint" style="font-size:12.5px">${esc(a.description)}</div></div></div>`).join('')) +
      card('Installed from Star Store', extra.map(a => `<div class="list-row"><img src="${esc(S.appIcon(a))}" width="34" height="34" style="border-radius:9px"><b class="grow">${esc(a.name)}</b><button class="btn small danger" data-uninstall="${esc(a.id)}">Uninstall</button></div>`).join('') ||
        `<div class="empty">Nothing yet. JStarx keeps things light: get only the apps you want from Star Store.</div><div style="padding-bottom:14px"><button class="btn primary small" id="open-store">${S.icon('bag')} Open Star Store</button></div>`);
  }

  async function systemUpdateCard() {
    const s = await call('update.system_status') || {};
    const text = { available: esc(s.message || 'A system update is ready'), downloading: `Downloading… ${s.progress != null ? s.progress + '%' : ''}`,
      installing: esc(s.message || 'Installing…'), ready: 'Installed: restart the Jetson to finish', 'up-to-date': 'The whole system is up to date',
      error: `Problem: ${esc(s.message || '')}` }[s.state] || 'Not checked yet';
    const busy = s.state === 'downloading' || s.state === 'installing';
    return card('Whole system (StarX Kernel, drivers, apps)', item(s.version ? `System ${esc(s.version)}` : 'System updates',
      text + '. If a new system does not start, JStarx goes back to the last one that worked.',
      `<button class="btn small" id="sys-check" ${busy ? 'disabled' : ''}>${S.icon('refresh')} Check</button>` +
      `<button class="btn primary small" id="sys-apply" ${s.state === 'available' ? '' : 'disabled'}>${S.icon('download')} Install</button>` +
      (s.state === 'ready' ? `<button class="btn small" id="sys-reboot">${S.icon('restart')} Restart</button>` : '')));
  }

  async function pageUpdates() {
    const st = await call('update.status') || {};
    const cur = (st.current || {});
    const avail = st.available;
    const stateText = { checking: 'Checking GitHub…', downloading: 'Downloading the update…', updated: `Updated to ${esc(st.version || '')}`, 'rolled-back': 'The last update had a problem, so it was undone.', error: `Problem: ${esc(st.message || '')}`, 'up-to-date': 'JStarx is up to date' }[st.state] || 'Not checked yet';
    return `<div class="big-stat"><div><span>JStarx version</span><b>${esc(cur.version || '?')}</b></div><div><span>Release name</span><b>${esc(cur.codename || '—')}</b></div><div><span>Last check</span><b style="font-size:16px">${st.checked ? new Date(st.checked * 1000).toLocaleString() : 'Never'}</b></div></div>` +
      card('', item(avail ? `Update available: ${esc(avail)}` : 'Updates', stateText,
        `<button class="btn small" id="up-check">${S.icon('refresh')} Check now</button><button class="btn primary small" id="up-apply" ${avail ? '' : 'disabled'}>${S.icon('download')} Update now</button>`) +
        item('Undo the last update', 'Go back to the version you had before. Your files and settings stay.', `<button class="btn small" id="up-undo">${S.icon('restart')} Undo</button>`)) +
      await systemUpdateCard() +
      card('Automatic updates', item('Update automatically', 'JStarx checks your GitHub repo every few hours and installs new versions. If an update breaks something, it is undone automatically.', toggle('updates.auto')) +
        item('Check every', '', slider('updates.interval_h', 1, 48, 1, ' h')) +
        item('Update from branch', 'Leave this as <b>main</b> unless you are testing.', `<input class="field" id="branch" value="${esc(get('updates.branch'))}" style="width:180px"><button class="btn small" id="branch-save">Save</button>`)) +
      card('What\'s new', `<ul style="margin:12px 0 14px;padding-left:20px;color:var(--text-2);line-height:1.7">${(cur.notes || []).map(n => `<li>${esc(n)}</li>`).join('') || '<li>No release notes.</li>'}</ul>`) +
      ((st.history || []).length ? card('History', st.history.slice(-8).reverse().map(h => `<div class="list-row">${S.icon(h.ok ? 'check' : 'close')}<div class="grow"><b>${esc(h.version)}</b><div class="faint" style="font-size:12.5px">${new Date(h.time * 1000).toLocaleString()} · ${esc(h.note || '')}</div></div></div>`).join('')) : '');
  }

  async function pageRepair() {
    const st = await call('repair.status') || {};
    const fixed = st.fixed || [], fixes = st.settings_fixes || [];
    return `<div class="big-stat"><div><span>Health</span><b>${st.state === 'problems' ? 'Needs repair' : 'Healthy'}</b></div><div><span>Last check</span><b style="font-size:16px">${st.time ? new Date(st.time * 1000).toLocaleString() : 'Not yet'}</b></div><div><span>Problems fixed</span><b>${fixed.length + fixes.length}</b></div></div>` +
      card('Auto-repair is always on', `<ul style="margin:12px 0;padding-left:20px;color:var(--text-2);line-height:1.7">
        <li>Every boot, JStarx checks its own files and fixes any that are missing or damaged.</li>
        <li>If the desktop crashes 3 times, it restarts in Safe Mode and undoes the last update.</li>
        <li>If the Jetson fails to start 3 times in a row, it goes back to the last version that worked.</li>
        <li>A watchdog reboots the Jetson if it ever freezes.</li></ul>`) +
      card('Repair now', item('Quick repair', 'Checks JStarx files and your settings. Takes a few seconds.', `<button class="btn primary small" data-repair="quick">${S.icon('wrench')} Repair</button>`) +
        item('Deep repair', 'Also checks every system file and re-downloads damaged ones. Can take a while.', `<button class="btn small" data-repair="deep">${S.icon('shield')} Deep repair</button>`) +
        item('Reset JStarx to factory', 'Puts the desktop and apps back to the version that came on the SD card. Your files stay.', `<button class="btn small danger" data-repair="factory">Reset</button>`) +
        item('Reset all settings', 'Wallpaper, dock and other choices go back to defaults.', `<button class="btn small danger" id="reset-settings">Reset settings</button>`)) +
      ((fixed.length || fixes.length) ? card('Last repair report', fixed.concat(fixes).map(f => `<div class="list-row">${S.icon('check')}<span class="grow">${esc(f)}</span></div>`).join('')) : '');
  }

  async function pageMemory() {
    const m = await call('memory.info') || {};
    const saver = await call('memory.saver') || { on: true };
    const ram = m.ram || {}, z = m.zram || {}, sf = m.swapfile || {};
    const gb = n => n ? (n / 1073741824).toFixed(1) + ' GB' : '0 GB';
    const pct = (a, b) => b ? Math.max(0, Math.min(100, Math.round(100 * a / b))) : 0;
    const bar = (name, used, total, note) => `<div class="item"><div class="txt"><div class="t">${name}</div><div class="s">${note}</div></div>
      <div class="ctl" style="min-width:300px;flex-direction:column;align-items:stretch;gap:6px"><div class="faint" style="text-align:right">${S.bytes(used || 0)} of ${S.bytes(total || 0)}</div>
      <div class="meter" style="height:10px"><i style="width:${pct(used, total)}%"></i></div></div></div>`;
    const ratio = z.ram_cost ? (z.stored / z.ram_cost).toFixed(1) : null;
    const apps = (m.apps || []).map(a => item(esc(a.name), `${S.bytes(a.ram)} in RAM${a.swap ? ` · ${S.bytes(a.swap)} moved to swap` : ''}`,
      `<div class="meter" style="width:180px"><i style="width:${pct(a.ram + a.swap, ram.total)}%"></i></div>`)).join('');
    return `<div class="big-stat" style="--n:3"><div><span>Usable memory</span><b>${gb(m.usable)}</b></div><div><span>RAM in use</span><b>${gb(ram.used)} / ${gb(ram.total)}</b></div><div><span>Moved to swap</span><b>${gb(m.swap_used)}</b></div></div>` +
      card('Where your memory is', bar('RAM', ram.used, ram.total, 'The Jetson\'s fast memory') +
        bar('Compressed RAM', z.used, z.total, ratio ? `Idle apps squeezed ${ratio}× so more fits` : 'Idle apps get squeezed here first') +
        bar('Swap file', sf.used, sf.total, 'On the SD card or SSD: idle apps wait here')) +
      card('Keep RAM free', item('Memory saver', 'Moves apps you are not using out of RAM early, so the app you are using stays fast.',
        `<button class="toggle" role="switch" aria-checked="${saver.on !== false}" id="mem-saver"></button>`) +
        item('Free up memory now', 'Moves idle app memory out of RAM right now.', `<button class="btn small primary" id="mem-free">${S.icon('bolt')} Free up</button>`)) +
      card('Apps using memory', apps || '<div class="faint" style="padding:12px 0">Nothing yet</div>');
  }
  setInterval(() => { if (current === 'memory' && !document.hidden) render(true); }, 4000);

  async function pageStorage() {
    const st = await call('system.stats') || { disk: {} };
    const d = st.disk || {}; const pct = d.total ? Math.round(100 * d.used / d.total) : 0;
    return card('', `<div style="padding:14px 0"><div class="status-line"><b class="grow">${S.bytes(d.used)} used of ${S.bytes(d.total)}</b><span class="faint">${S.bytes(d.free)} free</span></div>
      <div class="meter" style="height:12px;margin-top:10px"><i style="width:${pct}%"></i></div></div>`) +
      card('Free up space', item('Clean up', 'Deletes old JStarx versions older than two weeks and temporary files. Keeps the last working version for repair.', `<button class="btn small" id="clean">${S.icon('trash')} Clean up</button>`));
  }

  async function pageUsers() {
    return card('You', item('Your name', 'Used in greetings and the start menu.', `<input class="field" id="uname" value="${esc(get('user.name'))}" style="width:200px"><button class="btn small" id="uname-save">Save</button>`) +
      item('Password', 'Used to log in and to approve system changes.', `<input class="field" type="password" id="pw-old" placeholder="Current" autocomplete="current-password" style="width:130px"><input class="field" type="password" id="pw-new" placeholder="New" autocomplete="new-password" style="width:130px"><button class="btn small" id="pw-save">Change</button>`) +
      item('Log in automatically', 'Skip the password screen when the Jetson starts.', `<button class="btn small" data-sys="autologin" data-v="true">On</button><button class="btn small" data-sys="autologin" data-v="false">Off</button>`)) +
      card('Remote access', item('SSH', 'Lets you log in to this Jetson from another computer on your network.', `<button class="btn small" data-sys="ssh" data-v="true">On</button><button class="btn small" data-sys="ssh" data-v="false">Off</button>`)) +
      card('Privacy', item('No tracking', 'JStarx sends nothing about you anywhere. Updates only download files from your GitHub repo.', S.icon('shield')));
  }

  async function pageTime() {
    const zones = ['UTC', 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'America/Sao_Paulo', 'Europe/London', 'Europe/Berlin', 'Europe/Paris', 'Africa/Johannesburg', 'Asia/Dubai', 'Asia/Kolkata', 'Asia/Singapore', 'Asia/Tokyo', 'Australia/Sydney'];
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return card('', item('24-hour clock', '', toggle('clock.h24')) +
      item('Time zone', `Now: ${esc(tz)}`, `<select class="field" id="tz">${zones.map(z => `<option ${z === tz ? 'selected' : ''}>${z}</option>`).join('')}</select><button class="btn small" id="tz-save">Set</button>`));
  }

  async function pageAbout() {
    const i = await call('system.info') || {};
    const st = await call('system.stats') || {};
    return `<div style="display:flex;align-items:center;gap:22px;margin:6px 0 24px"><img src="${S.ctx.web}/icons/jstarx.svg" width="110" height="110" id="about-logo">
      <div><h1 style="margin:0">JStarx OS</h1><div class="muted" style="font-size:16px">${esc(i.os || '')}</div><div class="faint" style="margin-top:6px">Made by Storm · coded by Claude</div></div></div>` +
      card('', item('JStarx layer', '', `<b>${esc(i.layer || '')}</b>`) + item('StarX Kernel', '', `<b>${esc(i.kernel || '')}</b>`) + item('Computer', '', `<b>${esc(i.model || '')}</b>`) +
        item('Processor', '', `<b>${esc(i.cpu || '')} × ${i.cores || '?'}</b>`) + item('Memory', '', `<b>${S.bytes(i.memory)}</b>`) + item('Storage', '', `<b>${S.bytes(i.disk)}</b>`) +
        item('Up for', '', `<b>${S.duration(st.uptime)}</b>`) + item('Name on the network', '', `<b>${esc(i.hostname || '')}</b>`));
  }

  /* ---------------- events ---------------- */
  const main = $('#main');
  main.addEventListener('click', async e => {
    const t = e.target.closest('button'); if (!t) return;
    S.boing(t, .06);
    if (t.dataset.toggle) {
      await setSetting(t.dataset.toggle, t.getAttribute('aria-checked') !== 'true');
      if (t.dataset.toggle === 'spark.fast') await call('spark.service', { action: 'restart' }, 'Spark 1 restarted');
      return render(true);
    }
    if (t.dataset.choice) { const v = t.dataset.choice === 'appearance.bounce' ? +t.dataset.v : t.dataset.v; await setSetting(t.dataset.choice, v); return render(true); }
    if (t.dataset.power) { await call('power.set', { profile: t.dataset.v }, 'Power mode changed'); return render(true); }
    if (t.dataset.fan) { await call('power.fan', { mode: t.dataset.fan }, 'Fan updated'); return render(true); }
    if (t.dataset.pin) { const list = get('dock.pinned').slice(); const i = list.indexOf(t.dataset.pin); i >= 0 ? list.splice(i, 1) : list.push(t.dataset.pin); await setSetting('dock.pinned', list); return render(true); }
    if (t.dataset.join) { const pw = main.querySelector(`[data-pw="${CSS.escape(t.dataset.join)}"]`); t.textContent = 'Joining…'; const r = await call('net.wifi_connect', { ssid: t.dataset.join, password: pw ? pw.value : null }); S.toast(r && r.ok ? 'Connected!' : 'Could not connect. Check the password.'); return render(true); }
    if (t.dataset.uninstall) { await call('store.uninstall', { id: t.dataset.uninstall }, 'Uninstalled'); return render(true); }
    if (t.dataset.spark) { await call('spark.service', { action: t.dataset.spark }, 'Done'); return render(true); }
    if (t.dataset.repair) {
      t.disabled = true; t.innerHTML = `<span class="spin">${S.icon('refresh')}</span> Working…`;
      const r = await call('repair.run', { mode: t.dataset.repair });
      if (r) S.toast(r.fixed && r.fixed.length ? `Fixed ${r.fixed.length} problem(s)` : 'Everything looks good');
      return render(true);
    }
    if (t.dataset.sys) { await call('system.set', { key: t.dataset.sys, value: t.dataset.v === 'true' }, 'Saved'); return; }
    switch (t.id) {
      case 'wifi-radio': await call('net.wifi_radio', { on: t.getAttribute('aria-checked') !== 'true' }); return render(true);
      case 'rescan': return loadNets(true);
      case 'cast-now': return call('display.cast');
      case 'try-bounce': return S.spring($('#bounce-star'), { y: -26, scale: .6, rotate: -40 }, { y: 0, scale: 1, rotate: 0 });
      case 'reset-home': await call('home.reset', {}, 'Home screen reset'); return;
      case 'open-lp': return S.send('shell.open', { panel: 'launchpad' });
      case 'mute': await call('audio.set', { muted: t.getAttribute('aria-checked') !== 'true' }); return render(true);
      case 'ai247': await call('power.ai247', { on: t.getAttribute('aria-checked') !== 'true' }, '24/7 AI mode updated'); return render(true);
      case 'spark-dl': await setSetting('spark.model_url', $('#model-url').value.trim()); await call('spark.download', { url: $('#model-url').value.trim() }, 'Spark 1 is downloading. The island will tell you when it is ready.'); return render(true);
      case 'spark-import': await call('spark.import', { path: $('#model-path').value.trim() }, 'Model imported'); return render(true);
      case 'persona-save': return setSetting('spark.personality', $('#persona').value.trim().slice(0, 2000));
      case 'open-ai': return call('apps.launch', { id: 'ai' });
      case 'open-store': return call('apps.launch', { id: 'store' });
      case 'up-check': t.disabled = true; await call('update.check'); return render(true);
      case 'up-apply': t.disabled = true; t.textContent = 'Updating…'; await call('update.apply', {}, 'Update installed'); return render(true);
      case 'up-undo': await call('update.rollback', {}, 'Went back to the previous version'); return render(true);
      case 'branch-save': await call('update.config', { branch: $('#branch').value.trim() || 'main' }, 'Saved'); return render(true);
      case 'reset-settings': { const s = await call('settings.reset'); if (s) S.applySettings(s); S.toast('Settings reset'); return render(true); }
      case 'clean': t.disabled = true; t.textContent = 'Cleaning…'; { const r = await call('storage.clean'); if (r) S.toast(`Freed ${S.bytes(r.freed || 0)}`); } return render(true);
      case 'pw-save': {
        const o = $('#pw-old').value, n = $('#pw-new').value;
        if (n.length < 4) { S.toast('The new password needs at least 4 characters'); return; }
        const r = await call('system.password', { old: o, new: n }, null);
        if (r && r.changed) { $('#pw-old').value = ''; $('#pw-new').value = ''; S.toast('Password changed'); }
        return;
      }
      case 'sys-check': t.disabled = true; t.textContent = 'Checking…'; await call('update.system_check'); return render(true);
      case 'sys-reboot': return call('session.action', { action: 'reboot' });
      case 'sys-apply': await call('update.system_apply', {}, 'Installing the system update in the background'); return render(true);
      case 'mem-saver': await call('memory.saver', { on: t.getAttribute('aria-checked') !== 'true' }, 'Memory saver updated'); return render(true);
      case 'mem-free': { t.disabled = true; t.textContent = 'Freeing…'; const r = await call('memory.free'); if (r) S.toast(`Freed ${S.bytes(r.freed || 0)} of RAM`); return render(true); }
      case 'uname-save': return setSetting('user.name', $('#uname').value.trim().slice(0, 24) || 'Friend');
      case 'tz-save': return call('system.set', { key: 'timezone', value: $('#tz').value }, 'Time zone set');
    }
  });
  main.addEventListener('input', e => {
    const r = e.target.closest('[data-range]');
    if (r) r.nextElementSibling.textContent = r.value + (r.dataset.unit || '');
    if (e.target.id === 'vol') $('#vol-v').textContent = e.target.value + '%';
  });
  main.addEventListener('change', async e => {
    const r = e.target.closest('[data-range]');
    if (r) { await setSetting(r.dataset.range, parseFloat(r.value)); return; }
    const sel = e.target.closest('[data-select]');
    if (sel) { await setSetting(sel.dataset.select, sel.value); return; }
    if (e.target.id === 'vol') return call('audio.set', { volume: +e.target.value, muted: false });
    if (e.target.id === 'cast-device') return setSetting('cast.device', e.target.value.trim());
    const out = e.target.closest('[data-output]');
    if (out) { await call('display.set', out.dataset.kind === 'mode' ? { name: out.dataset.output, mode: out.value } : { name: out.dataset.output, scale: +out.value }, 'Display changed'); }
    if (e.target.dataset.pw) { /* password typed */ }
  });

  /* ---------------- navigation ---------------- */
  function renderNav(filter = '') {
    const f = filter.toLowerCase();
    $('#nav').innerHTML = PAGES.filter(p => !f || (p.name + ' ' + p.keys).toLowerCase().includes(f)).map(p =>
      `<button data-page="${p.id}" class="${p.id === current ? 'on' : ''}"><span class="ni ni-${p.color}">${S.icon(p.icon)}</span>${p.name}</button>`).join('');
  }
  $('#nav').addEventListener('click', e => { const b = e.target.closest('[data-page]'); if (b) { current = b.dataset.page; renderNav($('#search').value); render(); } });
  $('#search').addEventListener('input', e => renderNav(e.target.value));

  let renderSeq = 0;
  async function render(keepScroll) {
    const seq = ++renderSeq;
    const page = PAGES.find(p => p.id === current);
    const scroll = main.scrollTop;
    const body = await page.render();
    if (seq !== renderSeq) return;
    main.innerHTML = `<div class="${keepScroll ? '' : 'page-enter'}"><h1>${page.name}</h1>${body}</div>`;
    if (keepScroll) main.scrollTop = scroll;
    if (current === 'about' && !keepScroll) S.spring($('#about-logo'), { scale: .4, rotate: -30 }, { scale: 1, rotate: 0 }, { damping: .4 });
  }
  S.on('settings', () => { if (['appearance', 'dock'].includes(current)) render(true); });

  const hash = (location.hash || '').slice(1);
  if (PAGES.some(p => p.id === hash)) current = hash;
  renderNav(); render();
})();
