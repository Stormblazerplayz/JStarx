/* Star Store: browse and install official JStarx apps. */
(function () {
  'use strict';
  const S = window.StarX, $ = S.$, esc = S.esc;
  let catalog = { apps: [], categories: [] }, cat = 'All';
  const busy = {};

  document.querySelector('.hero .chip').innerHTML = `${S.icon('shield')} Every download is checked before it is installed`;

  async function load(refresh) {
    $('#note').textContent = refresh ? 'Checking GitHub for new apps…' : '';
    try { catalog = await S.call('store.catalog', { refresh: !!refresh }); } catch (e) { S.toast(e.message); }
    $('#note').textContent = '';
    render();
  }

  function render() {
    const f = catalog.apps.find(a => a.id === catalog.featured) || catalog.apps[0];
    if (f) $('#feat').innerHTML = `<img src="${esc(f.icon_url)}" alt=""><div class="grow"><div class="faint" style="font-size:12px;font-weight:800;letter-spacing:.08em">FEATURED</div>
      <div style="font-size:20px;font-weight:800">${esc(f.name)}</div><div class="muted" style="font-size:14px">${esc(f.description)}</div></div>${button(f)}`;
    $('#cats').innerHTML = ['All', ...catalog.categories, 'Installed'].map(c => `<button class="${c === cat ? 'on' : ''}" data-cat="${esc(c)}">${esc(c)}</button>`).join('');
    const q = $('#q').value.trim().toLowerCase();
    const list = catalog.apps.filter(a => (cat === 'All' || a.category === cat || (cat === 'Installed' && a.installed)) &&
      (!q || (a.name + ' ' + a.description).toLowerCase().includes(q)));
    $('#grid').innerHTML = list.map(a => `<div class="app-card" data-id="${esc(a.id)}"><img src="${esc(a.icon_url)}" alt="">
      <div class="grow"><div class="nm">${esc(a.name)}</div><div class="ds">${esc(a.description)}</div>
      <div class="meta"><span class="chip">${a.type === 'web' ? 'Light app' : 'Desktop app'}</span><span class="chip">${esc(a.size || '')}</span>${a.unfree ? '<span class="chip warn">Needs an account</span>' : ''}</div></div>
      <div class="act">${button(a)}<div class="prog" id="p-${esc(a.id)}">${esc(busy[a.id] || '')}</div></div></div>`).join('') || '<div class="empty">No apps match.</div>';
  }

  function button(a) {
    if (busy[a.id]) return `<button class="btn small" disabled><span class="spin">${S.icon('refresh')}</span> Working</button>`;
    return a.installed ? `<button class="btn small" data-open="${esc(a.id)}">Open</button><button class="btn small danger" data-remove="${esc(a.id)}">Remove</button>`
      : `<button class="btn small primary" data-install="${esc(a.id)}">${S.icon('download')} Get</button>`;
  }

  document.body.addEventListener('click', async e => {
    const c = e.target.closest('[data-cat]'); if (c) { cat = c.dataset.cat; render(); return; }
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.install) {
      const id = b.dataset.install; busy[id] = 'Starting…'; render();
      const card = document.querySelector(`.app-card[data-id="${CSS.escape(id)}"] img`);
      try {
        await S.call('store.install', { id });
        delete busy[id]; await load(false);
        S.toast('Installed! Find it in Launchpad.');
        const img = document.querySelector(`.app-card[data-id="${CSS.escape(id)}"] img`); if (img) S.launchBounce(img, 2);
      } catch (err) { delete busy[id]; render(); S.toast(err.message); }
      if (card) S.boing(card);
    }
    if (b.dataset.remove) { try { await S.call('store.uninstall', { id: b.dataset.remove }); S.toast('Removed'); } catch (err) { S.toast(err.message); } load(false); }
    if (b.dataset.open) { S.send('apps.launch', { id: b.dataset.open }); }
    if (b.id === 'refresh') load(true);
  });
  $('#q').addEventListener('input', render);
  S.on('store-progress', d => { busy[d.id] = d.text; const p = document.getElementById('p-' + d.id); if (p) p.textContent = d.text; });

  load(true).then(() => S.$$('.app-card').forEach((el, i) => S.spring(el, { y: 30, opacity: 0, scale: .95 }, { y: 0, opacity: 1, scale: 1 }, { delay: i * 40 })));
})();
