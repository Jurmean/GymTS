(() => {
  'use strict';
  const locale = document.body.dataset.locale;
  const zh = locale === 'zh';
  const root = new URL(document.body.dataset.root.replace(/\/?$/, '/'), location.href);
  const text = zh ? {
    copy: '复制', copied: '已复制', copyFailed: '请选择代码复制', loading: '正在加载本地搜索索引…',
    hint: '搜索当前语言的全部文档。', empty: '没有找到结果，试试组件名或更短的关键词。',
    failed: '搜索索引加载失败。请刷新页面重试，或使用侧栏导航。', results: n => `${n} 个结果`,
  } : {
    copy: 'Copy', copied: 'Copied', copyFailed: 'Select code to copy', loading: 'Loading the local search index…',
    hint: 'Search all documentation in this language.', empty: 'No results. Try a component name or a shorter query.',
    failed: 'The search index could not be loaded. Refresh to retry, or use the navigation.', results: n => `${n} results`,
  };
  const save = (key, value) => { try { localStorage.setItem(key, value); } catch (_) {} };
  const menu = document.querySelector('.menu-toggle');
  const sidebar = document.querySelector('.sidebar');
  const mobile = matchMedia('(max-width: 850px)');
  const syncSidebar = () => { sidebar.inert = mobile.matches && !document.body.classList.contains('nav-open'); };
  const closeMenu = (restoreFocus = true) => {
    const wasOpen = document.body.classList.contains('nav-open');
    document.body.classList.remove('nav-open'); menu.setAttribute('aria-expanded', 'false'); syncSidebar();
    if (wasOpen && restoreFocus && mobile.matches) menu.focus();
  };
  syncSidebar();
  mobile.addEventListener('change', () => { closeMenu(false); });
  menu.addEventListener('click', () => {
    const expanded = document.body.classList.toggle('nav-open');
    menu.setAttribute('aria-expanded', String(expanded));
    syncSidebar();
    if (expanded) document.querySelector('.search-button').focus();
  });
  document.querySelector('.nav-backdrop').addEventListener('click', () => closeMenu());
  document.querySelector('.sidebar-close').addEventListener('click', () => closeMenu());
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeMenu();
    if (event.key === 'Tab' && mobile.matches && document.body.classList.contains('nav-open')) {
      const focusable = [...sidebar.querySelectorAll('a[href],button:not([disabled])')].filter(node => node.getClientRects().length);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  document.querySelector('.theme-toggle').addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    save('gymts-theme', next);
  });
  document.querySelector('[data-language-switch]').addEventListener('click', event => {
    const link = event.currentTarget;
    save('gymts-lang', link.dataset.languageSwitch);
    if (location.hash) link.hash = location.hash;
  });
  save('gymts-lang', locale);
  document.querySelectorAll('article pre > code').forEach(code => {
    const button = document.createElement('button');
    button.className = 'copy-code'; button.type = 'button'; button.textContent = text.copy;
    button.setAttribute('aria-label', zh ? '复制代码' : 'Copy code');
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(code.textContent);
        button.textContent = text.copied;
      } catch (_) { button.textContent = text.copyFailed; }
      window.setTimeout(() => { button.textContent = text.copy; }, 1800);
    });
    code.parentElement.append(button);
  });
  document.querySelectorAll('article table').forEach(table => {
    const wrapper = document.createElement('div'); wrapper.className = 'table-scroll';
    wrapper.tabIndex = 0; wrapper.setAttribute('role', 'region');
    wrapper.setAttribute('aria-label', zh ? '可横向滚动的数据表格' : 'Scrollable data table');
    table.before(wrapper); wrapper.append(table);
  });
  const active = document.querySelector('.site-navigation [aria-current=page]');
  if (active && active.getBoundingClientRect().bottom > innerHeight - 50) {
    const nav = document.querySelector('.site-navigation');
    nav.scrollTop = active.offsetTop - nav.offsetTop - nav.clientHeight / 2;
  }
  const headings = [...document.querySelectorAll('article h2[id],article h3[id]')];
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (!visible.length) return;
      document.querySelectorAll('.page-toc a.active').forEach(link => link.classList.remove('active'));
      const href = `#${visible[0].target.id}`;
      document.querySelectorAll('.page-toc a').forEach(link => {
        if (decodeURIComponent(link.hash) === href) link.classList.add('active');
      });
    }, { rootMargin: '-5% 0px -65% 0px' });
    headings.forEach(heading => observer.observe(heading));
  }
  const dialog = document.getElementById('search-dialog');
  const input = document.getElementById('search-input');
  const status = document.getElementById('search-status');
  const results = document.getElementById('search-results');
  let indexPromise, lastFocus, timer, request = 0;
  const openSearch = () => {
    lastFocus = mobile.matches && sidebar.contains(document.activeElement) ? document.querySelector('.mobile-header .search-open') : document.activeElement;
    closeMenu(false);
    if (!dialog.open) dialog.showModal();
    input.focus(); input.select();
    if (input.value.trim()) search();
  };
  document.querySelectorAll('.search-open').forEach(button => button.addEventListener('click', openSearch));
  dialog.addEventListener('close', () => {
    const target = lastFocus && lastFocus.getClientRects().length && !(sidebar.inert && sidebar.contains(lastFocus)) ? lastFocus : document.querySelector(mobile.matches ? '.mobile-header .search-open' : '.search-button');
    if (target) target.focus();
  });
  dialog.addEventListener('click', event => { if (event.target === dialog) {
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  } });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && dialog.open) {
      event.preventDefault(); dialog.close(); return;
    }
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
    if (((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') || (event.key === '/' && !typing && !event.ctrlKey && !event.metaKey && !event.altKey)) {
      event.preventDefault(); openSearch();
    }
  });
  function terms(query) {
    const segments = query.toLowerCase().match(/[a-z0-9_]+|[\u3400-\u9fff]+/g) || [];
    return [...new Set(segments.flatMap(segment => /^[\u3400-\u9fff]{3,}$/.test(segment) ? [...segment].slice(0, -1).map((_, i) => segment.slice(i, i + 2)) : [segment]))];
  }
  function appendMarked(node, value, tokens) {
    const lower = value.toLowerCase();
    const matches = tokens.map(token => ({ at: lower.indexOf(token), len: token.length })).filter(match => match.at >= 0).sort((a, b) => a.at - b.at);
    if (!matches.length) { node.textContent = value; return; }
    let cursor = 0;
    for (const match of matches) {
      if (match.at < cursor) continue;
      node.append(document.createTextNode(value.slice(cursor, match.at)));
      const mark = document.createElement('mark'); mark.textContent = value.slice(match.at, match.at + match.len); node.append(mark);
      cursor = match.at + match.len;
    }
    node.append(document.createTextNode(value.slice(cursor)));
  }
  async function search() {
    const current = ++request;
    const query = input.value.trim(); const tokens = terms(query);
    results.replaceChildren();
    if (!tokens.length) { status.textContent = text.hint; return; }
    status.textContent = text.loading;
    if (!indexPromise) indexPromise = fetch(new URL('search.json', root)).then(response => {
      if (!response.ok) throw new Error('Search index unavailable');
      return response.json();
    }).catch(error => { indexPromise = null; throw error; });
    try {
      const index = await indexPromise;
      if (current !== request) return;
      const ranked = index.pages.map(page => {
        const title = page.title.toLowerCase(), body = page.text.toLowerCase();
        const matched = tokens.filter(token => title.includes(token) || body.includes(token));
        const score = matched.reduce((sum, token) => sum + (title.includes(token) ? 12 : 1), 0) + (title.includes(query.toLowerCase()) ? 20 : 0);
        return { page, score, count: matched.length };
      }).filter(item => item.count >= Math.ceil(tokens.length / 2)).sort((a, b) => b.score - a.score || a.page.title.localeCompare(b.page.title));
      status.textContent = ranked.length ? text.results(ranked.length) : text.empty;
      for (const { page } of ranked.slice(0, 40)) {
        const item = document.createElement('li'); const link = document.createElement('a'); link.href = new URL(page.url, root).href;
        const title = document.createElement('strong'); appendMarked(title, page.title, tokens);
        const snippet = document.createElement('p');
        const lower = page.text.toLowerCase(); const positions = tokens.map(token => lower.indexOf(token)).filter(i => i >= 0);
        const start = positions.length ? Math.max(0, Math.min(...positions) - 45) : 0;
        appendMarked(snippet, `${start ? '…' : ''}${page.text.slice(start, start + 180)}${page.text.length > start + 180 ? '…' : ''}`, tokens);
        link.append(title, snippet); item.append(link); results.append(item);
      }
    } catch (_) { if (current === request) status.textContent = text.failed; }
  }
  input.addEventListener('input', () => { window.clearTimeout(timer); timer = window.setTimeout(search, 100); });
})();
