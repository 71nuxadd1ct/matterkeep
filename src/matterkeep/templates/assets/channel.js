(function () {
  const messages = Array.from(document.querySelectorAll('#messages > .message:not(.system-message)'));
  if (!messages.length) return;

  // Populate sender dropdown from usernames present in the DOM
  const senderSelect = document.getElementById('filter-sender');
  const senders = [...new Set(
    messages
      .map(m => m.querySelector('.username'))
      .filter(Boolean)
      .map(el => el.textContent.trim())
  )].sort();

  senders.forEach(name => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    senderSelect.appendChild(opt);
  });

  // Parse "YYYY-MM-DD HH:MM" timestamps from the DOM
  function parseTs(el) {
    if (!el) return null;
    const txt = el.textContent.trim(); // e.g. "2026-01-15 10:23"
    const d = new Date(txt.replace(' ', 'T') + ':00Z');
    return isNaN(d) ? null : d;
  }

  function applyFilters() {
    const text   = document.getElementById('filter-text').value.trim().toLowerCase();
    const sender = senderSelect.value;
    const fromVal = document.getElementById('filter-from').value;
    const toVal   = document.getElementById('filter-to').value;
    const from = fromVal ? new Date(fromVal + 'T00:00:00Z') : null;
    const to   = toVal   ? new Date(toVal   + 'T23:59:59Z') : null;

    const active = text || sender || from || to;
    let visible = 0;

    document.querySelectorAll('#messages > .message.system-message').forEach(msg => {
      msg.classList.toggle('hidden', !!active);
    });

    messages.forEach(msg => {
      const bodyEl     = msg.querySelector('.message-body');
      const usernameEl = msg.querySelector('.username');
      const tsEl       = msg.querySelector('.timestamp');

      const body     = bodyEl     ? bodyEl.textContent.toLowerCase() : '';
      const username = usernameEl ? usernameEl.textContent.trim()    : '';
      const ts       = parseTs(tsEl);

      let show = true;
      if (text   && !body.includes(text))      show = false;
      if (sender && username !== sender)        show = false;
      if (from   && ts && ts < from)           show = false;
      if (to     && ts && ts > to)             show = false;

      msg.classList.toggle('hidden', !show);
      if (show) visible++;
    });

    const countEl = document.getElementById('filter-count');
    countEl.textContent = active ? `${visible} of ${messages.length} messages` : '';
  }

  ['filter-text', 'filter-sender', 'filter-from', 'filter-to'].forEach(id => {
    document.getElementById(id).addEventListener('input', applyFilters);
  });

  document.getElementById('filter-clear').addEventListener('click', () => {
    document.getElementById('filter-text').value  = '';
    senderSelect.value                             = '';
    document.getElementById('filter-from').value  = '';
    document.getElementById('filter-to').value    = '';
    applyFilters();
  });
})();
