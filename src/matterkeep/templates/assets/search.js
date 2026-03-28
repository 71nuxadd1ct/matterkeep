// matterkeep client-side search using lunr.js
// Lunr is loaded from CDN in index.html; this file wires up the UI.

(function () {
  if (typeof window.__LUNR_DOCS__ === 'undefined') return;

  const docs = window.__LUNR_DOCS__;
  if (!docs.length) return;

  const idx = lunr(function () {
    this.ref('id');
    this.field('body', { boost: 2 });
    this.field('channel_name');
    this.field('sender');
    docs.forEach((d) => this.add(d));
  });

  const docsById = {};
  docs.forEach((d) => { docsById[d.id] = d; });

  const input = document.getElementById('search-input');
  const resultsEl = document.getElementById('search-results');

  if (!input || !resultsEl) return;

  input.addEventListener('input', function () {
    const q = this.value.trim();
    if (!q) {
      resultsEl.innerHTML = '';
      resultsEl.classList.add('hidden');
      return;
    }

    let results;
    try {
      results = idx.search(q + '*');
    } catch (_) {
      results = [];
    }

    if (!results.length) {
      resultsEl.innerHTML = '<div class="search-result-item" style="color:var(--text-muted)">No results</div>';
      resultsEl.classList.remove('hidden');
      return;
    }

    const html = results.slice(0, 30).map((r) => {
      const doc = docsById[r.ref];
      if (!doc) return '';
      const snippet = doc.body.substring(0, 80).replace(/\n/g, ' ');
      const prefix = doc.channel_type === 'D' ? '@' : '#';
      return `<div class="search-result-item" data-channel="${doc.channel_id}" data-post="${doc.id}">
        <div class="search-result-channel">${prefix}${escHtml(doc.channel_name)} · ${escHtml(doc.sender || '')}</div>
        <div>${escHtml(snippet)}…</div>
      </div>`;
    }).join('');

    resultsEl.innerHTML = html;
    resultsEl.classList.remove('hidden');

    resultsEl.querySelectorAll('.search-result-item').forEach((el) => {
      el.addEventListener('click', function () {
        const channelId = this.dataset.channel;
        const postId = this.dataset.post;
        window.location.href = `${channelId}.html#post-${postId}`;
      });
    });
  });

  function escHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
})();

// Channel name filter — works on any page with #channel-filter
(function () {
  const input = document.getElementById('channel-filter');
  if (!input) return;
  input.addEventListener('input', function () {
    const q = this.value.trim().toLowerCase();
    document.querySelectorAll('#channel-list .channel-link').forEach(function (el) {
      const name = el.textContent.trim().toLowerCase();
      el.classList.toggle('channel-filter-hidden', !!q && !name.includes(q));
    });
  });
})();
