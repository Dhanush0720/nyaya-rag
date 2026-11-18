// Single-page app. All text is inserted with textContent (never innerHTML), so
// document text and model output cannot inject markup.
(function () {
  'use strict';
  var root = document.getElementById('app');
  var LABEL = {}; window.LANGS.forEach(function (l) { LABEL[l[0]] = l[1]; });
  var DOC_LANGS = ['en', 'hi', 'mr', 'te', 'ta', 'kn', 'ml', 'bn', 'gu', 'pa', 'or'];
  var EXTRA = { gu: 'ગુજરાતી', pa: 'ਪੰਜਾਬੀ', or: 'ଓଡ଼ିଆ' };
  Object.keys(EXTRA).forEach(function (k) { LABEL[k] = EXTRA[k]; });

  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
    del: function (k) { try { localStorage.removeItem(k); } catch (e) {} }
  };
  var S = { lang: store.get('lang') || 'en', token: store.get('token'), user: null, config: null, authMode: 'signin' };
  if (!window.I18N[S.lang]) S.lang = 'en';

  function t(key) { return (window.I18N[S.lang] && window.I18N[S.lang][key]) || window.I18N.en[key] || key; }

  function h(tag, attrs, kids) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === false || v == null) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    });
    (kids || []).forEach(function (c) {
      if (c == null || c === false) return;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return el;
  }

  function api(method, path, body, isForm) {
    var headers = {};
    if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
    var opts = { method: method, headers: headers };
    if (body && isForm) opts.body = body;
    else if (body) { headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (r.status === 401 && S.token && path.indexOf('/api/auth/') !== 0) { signOut(); throw new Error(data.detail || 'Session expired'); }
        if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : t('loadFail'));
        return data;
      });
    });
  }

  function setLang(code) {
    S.lang = code; store.set('lang', code);
    document.documentElement.lang = code;
    render();
  }
  function signOut() { S.token = null; S.user = null; store.del('token'); location.hash = ''; render(); }

  var ICON = {
    logo: '<svg width="34" height="34" viewBox="0 0 36 36" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 5v26M8 31h20M6 12h24M6 12l-4 10a4 4 0 0 0 8 0zM30 12l-4 10a4 4 0 0 0 8 0z"/></svg>',
    home: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="6" height="6" rx="1"/><rect x="11" y="3" width="6" height="6" rx="1"/><rect x="3" y="11" width="6" height="6" rx="1"/><rect x="11" y="11" width="6" height="6" rx="1"/></svg>',
    doc: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 2.5h7l3 3v12H5zM12 2.5v3h3M7.5 10h5M7.5 13h5"/></svg>',
    ask: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="9" r="5.5"/><path d="M13.2 13.2L17 17"/></svg>',
    scale: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 2.5v15M5 17.5h10M3.5 6.5h13M3.5 6.5L1.8 11a2.2 2.2 0 0 0 3.4 0zM16.5 6.5L14.8 11a2.2 2.2 0 0 0 3.4 0z"/></svg>'
  };
  function icon(svg) { var s = h('span', { 'aria-hidden': 'true', style: 'display:inline-flex;width:20px;height:20px' }); s.innerHTML = svg; return s; } // static strings only

  function langSelect(extraClass) {
    var sel = h('select', { 'aria-label': t('uiLang'), onchange: function (e) { setLang(e.target.value); } },
      window.LANGS.map(function (l) { return h('option', { value: l[0], text: l[1], selected: l[0] === S.lang }); }));
    if (extraClass) sel.className = extraClass;
    return sel;
  }

  // ---- auth ----------------------------------------------------------
  function authView() {
    var err = h('div', { class: 'msg err hidden', role: 'alert' });
    var reg = S.authMode === 'register';
    var nameF = h('input', { class: 'input', id: 'f-name', autocomplete: 'name' });
    var email = h('input', { class: 'input', id: 'f-email', type: 'email', autocomplete: 'email', required: true });
    var pass = h('input', { class: 'input', id: 'f-pass', type: 'password', autocomplete: reg ? 'new-password' : 'current-password', required: true, minlength: reg ? '8' : false });
    var btn = h('button', { class: 'btn', type: 'submit', text: reg ? t('register') : t('signin') });
    var form = h('form', { onsubmit: function (e) {
      e.preventDefault(); err.classList.add('hidden'); btn.disabled = true;
      var body = { email: email.value, password: pass.value };
      if (reg) body.name = nameF.value || email.value.split('@')[0];
      api('POST', reg ? '/api/auth/register' : '/api/auth/login', body).then(function (d) {
        S.token = d.token; S.user = d.user; store.set('token', d.token); location.hash = '#/dashboard'; render();
      }).catch(function (x) { err.textContent = x.message; err.classList.remove('hidden'); btn.disabled = false; });
    } }, [
      h('h2', { text: t('welcome') }),
      reg ? h('div', { class: 'field' }, [h('label', { for: 'f-name', text: t('name') }), nameF]) : null,
      h('div', { class: 'field' }, [h('label', { for: 'f-email', text: t('email') }), email]),
      h('div', { class: 'field' }, [h('label', { for: 'f-pass', text: t('password') }), pass]),
      err, btn,
      h('button', { class: 'btn ghost', type: 'button', text: reg ? t('toSignin') : t('toRegister'),
        onclick: function () { S.authMode = reg ? 'signin' : 'register'; render(); } })
    ]);
    var chips = h('div', { class: 'chips', role: 'group', 'aria-label': t('uiLang') }, window.LANGS.map(function (l) {
      return h('button', { class: 'chip', type: 'button', 'aria-pressed': String(l[0] === S.lang), text: l[1], onclick: function () { setLang(l[0]); } });
    }));
    var brand = h('div', { class: 'brand' }, [icon(ICON.logo), 'Nyaya RAG']);
    return h('div', { class: 'auth' }, [
      h('section', { class: 'side' }, [brand, h('h1', { text: t('headline') }), h('p', { text: t('sub') })]),
      h('section', { class: 'form' }, [h('div', { style: 'width:100%;max-width:420px;display:flex;flex-direction:column;gap:24px' }, [chips, form])])
    ]);
  }

  // ---- shell ---------------------------------------------------------
  var ROUTES = [['dashboard', 'dashboard', 'home'], ['documents', 'documents', 'doc'], ['ask', 'workspace', 'ask'], ['audit', 'audit', 'scale']];
  function shell(active, content) {
    var navLinks = ROUTES.map(function (r) {
      var a = h('a', { class: 'item', href: '#/' + r[0], 'aria-current': r[0] === active ? 'page' : false }, [icon(ICON[r[2]]), t(r[1])]);
      return a;
    });
    var nav = h('nav', { class: 'nav', 'aria-label': 'Main' }, [
      h('div', { class: 'brand' }, [icon(ICON.logo), 'Nyaya RAG']),
      h('div', { style: 'display:flex;flex-direction:column;gap:4px' }, navLinks),
      h('div', { class: 'grow' }, [
        h('span', { style: 'font-size:14px;color:#D5DEEA', text: S.user ? S.user.email : '' }),
        h('label', { style: 'font-size:14px;color:#D5DEEA', text: t('uiLang') }), langSelect(),
        h('button', { class: 'signout', type: 'button', text: t('signout'), onclick: signOut })
      ])
    ]);
    var top = h('div', { class: 'topbar' }, [h('div', { class: 'brand', style: 'font-size:20px' }, [icon(ICON.logo), 'Nyaya RAG']), langSelect()]);
    var bar = h('nav', { class: 'mobilebar', 'aria-label': 'Main' }, ROUTES.map(function (r) {
      return h('a', { href: '#/' + r[0], 'aria-current': r[0] === active ? 'page' : false }, [icon(ICON[r[2]]), t(r[1])]);
    }));
    return h('div', null, [top, h('div', { class: 'shell' }, [nav, h('main', { class: 'main' }, content)]), bar]);
  }

  function badgeFor(status) {
    var cls = status === 'indexed' ? 'ok' : 'na';
    return h('span', { class: 'badge ' + cls, text: status });
  }
  function pct(v) { return v == null ? '–' : Math.round(v * 100); }
  function bar(v) { return h('div', { class: 'barrow' }, [h('div', { class: 'bar' }, [h('i', { style: 'width:' + Math.max(0, Math.min(100, (v || 0) * 100)) + '%' })]), h('span', { text: String(pct(v)) })]); }
  function modeNote() {
    return S.config && S.config.mode !== 'gemini' ? h('div', { class: 'msg info', text: t('offlineNote') }) : null;
  }
  function loading() { return h('p', { class: 'muted', text: t('working') }); }

  // ---- dashboard -----------------------------------------------------
  function dashboardView() {
    var box = h('div', { style: 'display:flex;flex-direction:column;gap:24px' }, [loading()]);
    api('GET', '/api/stats').then(function (s) {
      var max = Math.max.apply(null, [1].concat(s.by_language.map(function (x) { return x.count; })));
      var rows = s.recent.length ? s.recent.map(function (d) {
        return h('tr', null, [
          h('td', null, [h('a', { href: '#/ask/' + d.id, text: d.title })]),
          h('td', { text: LABEL[d.lang] || d.lang }), h('td', { text: d.doc_type || '–' }), h('td', null, [badgeFor(d.status)])]);
      }) : [h('tr', null, [h('td', { colspan: '4', class: 'muted', text: t('none') })])];
      var stat = function (n, label) { return h('div', { class: 'card stat' }, [h('span', { class: 'muted', text: label }), h('span', { class: 'n', text: String(n) })]); };
      box.replaceChildren(
        modeNote(),
        h('div', { class: 'grid' }, [stat(s.documents, t('docsCount')), stat(s.summaries, t('sumCount')), stat(s.languages, t('langCount')),
          stat(s.grounded_pct == null ? '–' : s.grounded_pct + '%', t('grounded'))]),
        h('div', { class: 'cols' }, [
          h('section', { class: 'card', style: 'flex-grow:2' }, [h('h2', { text: t('recent') }),
            h('div', { class: 'tablewrap' }, [h('table', null, [h('thead', null, [h('tr', null, [h('th', { text: t('documents') }), h('th', { text: t('language') }), h('th', { text: t('type') }), h('th', { text: t('status') })])]), h('tbody', null, rows)])])]),
          h('section', { class: 'card' }, [h('h2', { text: t('byLang') })].concat(s.by_language.length ? s.by_language.map(function (x) {
            return h('div', null, [h('div', { class: 'row', style: 'gap:8px' }, [h('span', { text: LABEL[x.lang] || x.lang }), h('span', { class: 'muted', text: String(x.count) })]),
              h('div', { class: 'bar' }, [h('i', { style: 'width:' + (100 * x.count / max) + '%' })])]);
          }) : [h('p', { class: 'muted', text: t('none') })]))
        ])
      );
    }).catch(function (e) { box.replaceChildren(h('div', { class: 'msg err', text: e.message })); });
    return [h('div', { class: 'row' }, [h('h1', { text: t('dashboard') }), h('a', { class: 'btn', href: '#/documents', text: t('upload') })]), box];
  }

  // ---- documents -----------------------------------------------------
  function documentsView() {
    var msg = h('div', { class: 'msg err hidden', role: 'alert' });
    var title = h('input', { class: 'input', id: 'd-title', maxlength: '200' });
    var type = h('input', { class: 'input', id: 'd-type', maxlength: '60', placeholder: 'Contract, judgment, notice…' });
    var lang = h('select', { class: 'input', id: 'd-lang' }, [h('option', { value: '', text: t('auto') })].concat(DOC_LANGS.map(function (c) { return h('option', { value: c, text: LABEL[c] || c }); })));
    var file = h('input', { class: 'input', id: 'd-file', type: 'file', accept: '.txt,.pdf,.docx', style: 'padding:10px 14px;height:auto' });
    var text = h('textarea', { class: 'input', id: 'd-text' });
    var btn = h('button', { class: 'btn', type: 'submit', text: t('add') });
    var list = h('div', null, [loading()]);

    function loadList() {
      api('GET', '/api/documents').then(function (docs) {
        if (!docs.length) { list.replaceChildren(h('p', { class: 'muted', text: t('none') })); return; }
        list.replaceChildren(h('div', { class: 'tablewrap' }, [h('table', null, [h('tbody', null, docs.map(function (d) {
          return h('tr', null, [
            h('td', null, [h('a', { href: '#/ask/' + d.id, text: d.title })]), h('td', { text: LABEL[d.lang] || d.lang }), h('td', { text: String(d.n_chunks) }),
            h('td', null, [h('button', { class: 'btn danger', type: 'button', text: t('remove'), onclick: function () {
              if (confirm(t('confirmDelete'))) api('DELETE', '/api/documents/' + d.id).then(loadList).catch(function (e) { msg.textContent = e.message; msg.classList.remove('hidden'); });
            } })])]);
        }))])]));
      }).catch(function (e) { list.replaceChildren(h('div', { class: 'msg err', text: e.message })); });
    }
    loadList();

    var form = h('form', { class: 'card', onsubmit: function (e) {
      e.preventDefault(); msg.classList.add('hidden'); btn.disabled = true; btn.textContent = t('working');
      var fd = new FormData();
      fd.append('title', title.value); fd.append('lang', lang.value); fd.append('doc_type', type.value); fd.append('text', text.value);
      if (file.files[0]) fd.append('file', file.files[0]);
      api('POST', '/api/documents', fd, true).then(function (r) { location.hash = '#/ask/' + r.id; })
        .catch(function (x) { msg.textContent = x.message; msg.classList.remove('hidden'); btn.disabled = false; btn.textContent = t('add'); });
    } }, [
      h('h2', { text: t('upload') }),
      h('div', { class: 'field' }, [h('label', { for: 'd-title', text: t('docTitle') }), title]),
      h('div', { class: 'cols' }, [
        h('div', { class: 'field' }, [h('label', { for: 'd-type', text: t('type') }), type]),
        h('div', { class: 'field' }, [h('label', { for: 'd-lang', text: t('docLang') }), lang])]),
      h('div', { class: 'field' }, [h('label', { for: 'd-file', text: t('chooseFile') }), file]),
      h('div', { class: 'field' }, [h('label', { for: 'd-text', text: t('orPaste') }), text]),
      msg, btn]);
    return [h('h1', { text: t('documents') }), modeNote(), h('div', { class: 'cols' }, [form, h('section', { class: 'card' }, [h('h2', { text: t('recent') }), list])])];
  }

  // ---- workspace (summarize, ask, review) -----------------------------
  function renderCited(container, answer, onCite) {
    // Turn [n] markers into small buttons, everything else stays text.
    container.replaceChildren();
    answer.split(/(\[\d+\])/).forEach(function (part) {
      var m = /^\[(\d+)\]$/.exec(part);
      if (m) container.appendChild(h('button', { class: 'cite', type: 'button', text: m[1], 'aria-label': t('sources') + ' ' + m[1], onclick: function () { onCite(+m[1]); } }));
      else if (part) container.appendChild(document.createTextNode(part));
    });
  }

  function workspaceView(docId) {
    var ansLang = S.lang;
    var out = h('div', { style: 'display:flex;flex-direction:column;gap:20px' });
    var picker = h('div', { class: 'card' }, [loading()]);
    var srcBox = h('div');

    function showSources(passages) {
      srcBox.replaceChildren(h('h2', { text: t('sources') }), h('div', { style: 'height:12px' }));
      passages.forEach(function (p) {
        srcBox.appendChild(h('p', { class: 'passage', id: 'p-' + p.n }, [h('span', { class: 'cite num', text: String(p.n) }), h('span', { text: p.text })]));
      });
    }
    function flash(n) { var el = document.getElementById('p-' + n); if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); el.classList.add('flash'); setTimeout(function () { el.classList.remove('flash'); }, 1500); } }

    function result(title, r) {
      var line = h('p', { class: 'answer' });
      var kids = [h('div', { class: 'row', style: 'gap:8px' }, [h('h2', { text: title }),
        h('span', { class: 'badge ' + (r.not_found ? 'na' : 'ok'), text: r.grounding.cited + '/' + r.grounding.sentences + ' ' + t('cited') })])];
      if (r.not_found) kids.push(h('div', { class: 'msg info', text: t('notFound') }));
      else { renderCited(line, r.answer, flash); kids.push(line); }
      var card = h('section', { class: 'card' }, kids);
      out.replaceChildren(card); showSources(r.passages);
    }
    function busy(btns, on) { btns.forEach(function (b) { b.disabled = on; }); }
    function fail(e) { out.replaceChildren(h('div', { class: 'msg err', role: 'alert', text: e.message })); }

    function build(doc) {
      var sumBtn = h('button', { class: 'btn', type: 'button', text: t('summarize') });
      var revBtn = h('button', { class: 'btn ghost', type: 'button', text: t('review') });
      var q = h('input', { class: 'input', id: 'q', maxlength: '1000', placeholder: t('question') });
      var askBtn = h('button', { class: 'btn', type: 'submit', text: t('send') });
      var all = [sumBtn, revBtn, askBtn];
      var chips = h('div', { class: 'chips', role: 'group', 'aria-label': t('answerLang') }, window.LANGS.map(function (l) {
        var b = h('button', { class: 'chip', type: 'button', 'aria-pressed': String(l[0] === ansLang), text: l[1] });
        b.addEventListener('click', function () { ansLang = l[0]; chips.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); }); b.setAttribute('aria-pressed', 'true'); });
        return b;
      }));
      sumBtn.addEventListener('click', function () { busy(all, true); out.replaceChildren(loading()); api('POST', '/api/documents/' + doc.id + '/summarize', { lang: ansLang }).then(function (r) { result(t('summary'), r); }).catch(fail).then(function () { busy(all, false); }); });
      revBtn.addEventListener('click', function () {
        busy(all, true); out.replaceChildren(loading());
        api('POST', '/api/documents/' + doc.id + '/review', { lang: ansLang }).then(function (r) {
          if (r.message) { out.replaceChildren(h('div', { class: 'msg info', text: t('needsKey') })); return; }
          out.replaceChildren(h('section', { class: 'card' }, [h('h2', { text: t('review') })].concat(r.items.length ? r.items.map(function (it) {
            return h('div', { style: 'display:flex;flex-wrap:wrap;gap:10px 14px;padding:10px 0;border-bottom:1px solid #ECE9E0' }, [
              h('span', { class: 'badge ' + it.risk, text: it.risk }),
              h('div', { style: 'flex:1 1 240px' }, [h('div', { style: 'font-weight:500', text: (it.clause ? '[' + it.clause + '] ' : '') + it.title }), h('div', { class: 'muted', text: it.note })])]);
          }) : [h('p', { class: 'muted', text: t('none') })])));
          showSources(r.passages);
        }).catch(fail).then(function () { busy(all, false); });
      });
      var form = h('form', { class: 'row', style: 'flex-wrap:wrap;gap:10px;justify-content:stretch', onsubmit: function (e) {
        e.preventDefault(); if (!q.value.trim()) return; busy(all, true); out.replaceChildren(loading());
        api('POST', '/api/documents/' + doc.id + '/ask', { question: q.value, lang: ansLang }).then(function (r) { result(t('workspace'), r); }).catch(fail).then(function () { busy(all, false); });
      } }, [h('label', { for: 'q', style: 'position:absolute;left:-9999px', text: t('question') }), h('div', { style: 'flex:1 1 260px;min-width:0' }, [q]), askBtn]);
      picker.replaceChildren(h('h2', { text: doc.title }),
        h('p', { class: 'muted', style: 'margin:0', text: (LABEL[doc.lang] || doc.lang) + ' · ' + doc.n_chunks + ' passages' }),
        h('div', null, [h('div', { class: 'muted', style: 'font-size:14px;margin-bottom:6px', text: t('answerLang') }), chips]),
        h('div', { class: 'chips' }, [sumBtn, revBtn]), form);
    }

    api('GET', '/api/documents').then(function (docs) {
      if (!docs.length) { picker.replaceChildren(h('p', { class: 'muted', text: t('none') }), h('a', { class: 'btn', href: '#/documents', text: t('upload') })); return; }
      if (!docId) {
        picker.replaceChildren(h('h2', { text: t('selectDoc') }), h('div', { style: 'display:flex;flex-direction:column;gap:8px' }, docs.map(function (d) {
          return h('a', { class: 'btn ghost', style: 'justify-content:flex-start', href: '#/ask/' + d.id, text: d.title + ' · ' + (LABEL[d.lang] || d.lang) });
        })));
        return;
      }
      var doc = docs.filter(function (d) { return d.id === docId; })[0];
      if (!doc) { picker.replaceChildren(h('div', { class: 'msg err', text: t('loadFail') })); return; }
      build(doc);
    }).catch(function (e) { picker.replaceChildren(h('div', { class: 'msg err', text: e.message })); });

    return [h('h1', { text: t('workspace') }), modeNote(), h('div', { class: 'cols' }, [h('div', { style: 'display:flex;flex-direction:column;gap:20px' }, [picker, out]), h('section', { class: 'card' }, [srcBox])])];
  }

  // ---- audit ---------------------------------------------------------
  function auditView() {
    var box = h('div', { style: 'display:flex;flex-direction:column;gap:20px' }, [h('p', { class: 'muted', text: t('runFirst') })]);
    var btn = h('button', { class: 'btn', type: 'button', text: t('runAudit') });

    function status(s) {
      var map = { ok: ['ok', t('withinLimit')], review: ['review', t('review2')], no_pairs: ['na', t('noPairs')], no_data: ['na', t('noData')], needs_gemini: ['na', t('needsGemini')] };
      var m = map[s] || ['na', s]; return h('span', { class: 'badge ' + m[0], text: m[1] });
    }
    function show(a) {
      if (!a || !a.quality) return;
      var q = a.quality;
      box.replaceChildren(
        q.gap ? h('div', { class: 'msg info', text: t('gap') + ': ' + q.gap.points + ' pts (' + (LABEL[q.gap.best] || q.gap.best) + ' → ' + (LABEL[q.gap.worst] || q.gap.worst) + ')' }) : null,
        h('div', { class: 'cols' }, [
          h('section', { class: 'card' }, [h('h2', { text: t('quality') }), h('div', { class: 'tablewrap' }, [h('table', null, [
            h('thead', null, [h('tr', null, [h('th', { text: t('language') }), h('th', { text: t('docsCol') }), h('th', { text: t('recall') }), h('th', { text: t('groundedCol') })])]),
            h('tbody', null, q.by_language.length ? q.by_language.map(function (r) {
              return h('tr', null, [h('td', { text: LABEL[r.lang] || r.lang }), h('td', { text: String(r.docs) }), h('td', null, [bar(r.recall_at_5)]), h('td', null, [bar(r.grounded_ratio)])]);
            }) : [h('tr', null, [h('td', { colspan: '4', class: 'muted', text: t('none') })])])])])]),
          h('section', { class: 'card' }, [h('h2', { text: t('cf') })].concat(a.counterfactual.map(function (c) {
            return h('div', { class: 'row', style: 'gap:8px;border-bottom:1px solid #ECE9E0;padding-bottom:10px' }, [
              h('span', { text: c.attribute.replace('_', ' ') }),
              h('span', { style: 'display:inline-flex;gap:10px;align-items:center' }, [c.flip_rate == null ? null : h('span', { text: t('flip') + ' ' + (c.flip_rate * 100).toFixed(1) + '% (' + c.tested + ')' }), status(c.status)])]);
          })))
        ]));
    }
    api('GET', '/api/audit/latest').then(show).catch(function () {});
    btn.addEventListener('click', function () {
      btn.disabled = true; box.replaceChildren(loading());
      api('POST', '/api/audit/run').then(show).catch(function (e) { box.replaceChildren(h('div', { class: 'msg err', text: e.message })); }).then(function () { btn.disabled = false; });
    });
    return [h('div', { class: 'row' }, [h('div', null, [h('h1', { text: t('audit') }), h('p', { class: 'muted', style: 'margin:4px 0 0;max-width:640px', text: t('auditSub') })]), btn]), modeNote(), box];
  }

  // ---- router --------------------------------------------------------
  function render() {
    document.documentElement.lang = S.lang;
    if (!S.token) { root.replaceChildren(authView()); return; }
    var parts = (location.hash || '#/dashboard').slice(2).split('/');
    var page = parts[0] || 'dashboard';
    var views = { dashboard: dashboardView, documents: documentsView, ask: function () { return workspaceView(parts[1]); }, audit: auditView };
    if (!views[page]) page = 'dashboard';
    root.replaceChildren(shell(page, views[page]()));
  }

  window.addEventListener('hashchange', render);
  api('GET', '/api/config').then(function (c) { S.config = c; }).catch(function () {}).then(function () {
    if (!S.token) { render(); return; }
    api('GET', '/api/me').then(function (u) { S.user = u; render(); }).catch(function () { signOut(); });
  });
})();
