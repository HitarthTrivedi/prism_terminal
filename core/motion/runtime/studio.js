/* Prism Motion Studio — browser workspace over the Motion runtime.
 *
 * Every change the owner makes is one of the two record kinds
 * core/motion/studio.py sanitises (node / scene). Records are posted to
 * /preview, the server applies them to the spec, validates, resolves and
 * returns the resolved spec, and this page reloads the SAME runtime the
 * renderer films with it. Nothing here styles a node directly, so what the
 * preview shows is what the export will be.
 *
 * Layout: the four frame layers (backdrop, stage, vignette, grain) are
 * wrapped in #motion-frame, kept at the real frame size and scaled as one
 * unit — never the stage, whose transform the camera owns. */
(function () {
  'use strict';
  var SOURCE = window.__MOTION_SOURCE__ || {scenes: []};
  var PREVIEW = window.__MOTION_PREVIEW__ || {resolved: SOURCE, review: [], errors: [], warnings: []};
  var SAFE = window.__MOTION_SAFE__ || {};
  var EASINGS = window.__MOTION_EASINGS__ || ['power2.inOut'];
  var SHOTS = window.__MOTION_SHOTS__ || ['hold'];
  var runtime = window.__runtime;
  var W = (SOURCE.project || {}).width || 1080, H = (SOURCE.project || {}).height || 1920;
  var FPS = (SOURCE.project || {}).fps || 30;
  var edits = new Map(), undo = [], redo = [], current = 0, selected = null, activeThread = null;
  var playing = false, time = 0, zoom = 1, base = 1, drag = null, saveTimer, previewTimer, previewing = false, dirty = false;
  (window.__MOTION_EDITS__ || []).forEach(function (e) { edits.set(key(e), e); });

  // ── records ──────────────────────────────────────────────────────────────
  function q(s, root) { return (root || document).querySelector(s); }
  function all() { return Array.from(edits.values()); }
  function key(e) { return e.root ? e.scene + '/root' : e.scene + '/' + e.node; }
  function nodeRecord(sceneNo, id) {
    var k = sceneNo + '/' + id;
    if (!edits.has(k)) edits.set(k, {scene: sceneNo, node: id, dx: 0, dy: 0, scale: 1, rotation: 0});
    return edits.get(k);
  }
  function sceneRecord(sceneNo) {
    var k = sceneNo + '/root';
    if (!edits.has(k)) edits.set(k, {scene: sceneNo, root: true});
    return edits.get(k);
  }
  function saveState() { undo.push(JSON.stringify(all())); if (undo.length > 80) undo.shift(); redo = []; buttons(); }
  function restore(state) { edits.clear(); JSON.parse(state).forEach(function (e) { edits.set(key(e), e); }); preview(true); }
  function buttons() { q('#ms-undo').disabled = !undo.length; q('#ms-redo').disabled = !redo.length; }
  function status(text) { q('#ms-status').textContent = text; }
  function post(path, extra, done) {
    var body = {edits: all()}; Object.assign(body, extra || {});
    fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (data) { done(true, data); }).catch(function () { done(false); });
  }
  function autosave() {
    dirty = true; status('Saving…'); clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { post('/autosave', null, function (ok) { status(ok ? 'Saved' : 'Save failed'); dirty = !ok; }); }, 700);
  }

  // ── the spec, as the runtime plays it ────────────────────────────────────
  function resolved() { return PREVIEW.resolved || SOURCE; }
  function scenes() { return resolved().scenes || []; }
  function sourceScene(i) { return (SOURCE.scenes || [])[i] || {nodes: []}; }
  function total() { var s = scenes(); var last = s[s.length - 1]; return last ? (last.start || 0) + (last.duration || 0) : 0; }
  function sceneAt(t) { var s = scenes(); for (var i = 0; i < s.length; i++) if (t < (s[i].start || 0) + (s[i].duration || 0)) return i; return Math.max(0, s.length - 1); }
  function threads() { return ((resolved()._continuity_compiled || {}).threads) || {}; }
  function walk(nodes, fn, depth, parent) {
    (nodes || []).forEach(function (n) { if (!n || typeof n !== 'object') return; fn(n, depth || 0, parent || null); walk(n.children, fn, (depth || 0) + 1, n); });
  }
  function findNode(sceneNo, id) { var hit = null; walk(sourceScene(sceneNo).nodes, function (n) { if (!hit && String(n.id) === String(id)) hit = n; }); return hit; }
  function load() {
    runtime.loadSpec(JSON.parse(JSON.stringify(resolved())));
    seek(time);
    highlight();
  }
  function preview(immediate) {
    clearTimeout(previewTimer);
    var run = function () {
      if (previewing) { previewTimer = setTimeout(run, 120); return; }
      previewing = true; status('Previewing…');
      post('/preview', null, function (ok, data) {
        previewing = false;
        if (ok && data && data.resolved) { PREVIEW = data; load(); diagnostics(); timeline(); scenesList(); sceneUI(); status(dirty ? 'Saving…' : 'Ready'); }
        else status('Preview failed');
        autosave();
      });
    };
    previewTimer = setTimeout(run, immediate ? 0 : 160);
  }

  // ── time ─────────────────────────────────────────────────────────────────
  function fmt(t) { var n = Math.max(0, t); return Math.floor(n / 60) + ':' + ('0' + Math.floor(n % 60)).slice(-2) + '.' + ('00' + Math.floor(n % 1 * 100)).slice(-2); }
  function seek(t) {
    time = Math.max(0, Math.min(total(), t));
    runtime.seek(Math.round(time * FPS));
    var next = sceneAt(time);
    if (next !== current) { current = next; sceneUI(); scenesList(); layers(); inspector(); }
    q('#ms-time').textContent = fmt(time) + ' / ' + fmt(total());
    q('#ms-scrub').value = time;
    q('#ms-timeline').style.setProperty('--playhead', (100 * time / Math.max(0.001, total())) + '%');
  }
  function showScene(i, at) {
    current = Math.max(0, Math.min(scenes().length - 1, i));
    var s = scenes()[current] || {start: 0, duration: 1};
    var review = PREVIEW.review && PREVIEW.review[current];
    seek(review ? review[at || 'settled'] : (s.start + s.duration * 0.6));
    refresh();
  }
  function toggle() {
    if (playing) { playing = false; return; }
    playing = true; q('#ms-play').textContent = '❚❚ Pause';
    var previous = performance.now();
    (function loop(now) {
      if (!playing) { q('#ms-play').textContent = '▶ Play'; return; }
      seek(time + (now - previous) / 1000); previous = now;
      if (time < total()) requestAnimationFrame(loop); else playing = false;
    })(previous);
  }

  // ── the frame ────────────────────────────────────────────────────────────
  var viewport = document.createElement('div'); viewport.id = 'motion-viewport';
  var frame = document.createElement('div'); frame.id = 'motion-frame';
  var backdrop = document.getElementById('backdropCanvas'), stage = document.getElementById('stage');
  var vignette = document.getElementById('vignetteOverlay'), grain = document.getElementById('grainOverlay');
  document.body.insertBefore(viewport, backdrop);
  viewport.appendChild(frame);
  [backdrop, stage, vignette, grain].forEach(function (el) { if (el) frame.appendChild(el); });
  var safe = document.createElement('div'); safe.id = 'motion-safe';
  if (SAFE.vertical) {
    safe.innerHTML = '<div class="band top" style="height:' + SAFE.top + 'px"><span class="tag" style="top:' + (SAFE.top - 44) + 'px">platform UI</span></div>'
      + '<div class="band bottom" style="height:' + (H - SAFE.bottom) + 'px"><span class="tag" style="top:8px">captions · buttons</span></div>'
      + '<div class="side" style="left:0;width:' + SAFE.left + 'px"></div><div class="side" style="right:0;width:' + (W - SAFE.right) + 'px"></div>'
      + '<div class="zone" style="top:' + SAFE.title.top + 'px;height:' + (SAFE.title.bottom - SAFE.title.top) + 'px"><span class="tag" style="top:6px;font-size:22px">title zone</span></div>'
      + '<div class="zone" style="top:' + SAFE.action.top + 'px;height:' + (SAFE.action.bottom - SAFE.action.top) + 'px"><span class="tag" style="top:6px;font-size:22px">action zone</span></div>';
  } else {
    safe.innerHTML = '<div class="zone" style="top:' + (SAFE.top || 0) + 'px;height:' + ((SAFE.bottom || H) - (SAFE.top || 0)) + 'px"></div>';
  }
  frame.appendChild(safe);
  function fit() {
    frame.style.width = W + 'px'; frame.style.height = H + 'px';
    var w = viewport.clientWidth - 48, h = viewport.clientHeight - 36;
    base = Math.max(0.05, Math.min(w / W, h / H));
    var scale = base * zoom;
    frame.style.transform = 'translate(' + Math.max(24, (viewport.clientWidth - W * scale) / 2) + 'px,18px) scale(' + scale + ')';
  }

  // ── selection ────────────────────────────────────────────────────────────
  function hostOf(id) { return stage.querySelector('[data-motion-id="' + CSS.escape(String(id)) + '"]'); }
  function boxOf(id) { var h = hostOf(id); return h && h.firstElementChild; }
  function highlight() {
    stage.querySelectorAll('.__motion-sel,.__motion-thread').forEach(function (el) { el.classList.remove('__motion-sel'); el.classList.remove('__motion-thread'); });
    if (activeThread) (threads()[activeThread] || []).forEach(function (item) { var b = boxOf(item.node); if (b) b.classList.add('__motion-thread'); });
    if (selected) { var b = boxOf(selected); if (b) b.classList.add('__motion-sel'); }
  }
  function pick(id) { selected = id || null; highlight(); layers(); inspector(); }
  function label(n) {
    if (!n) return 'nothing';
    var text = n.type === 'text' ? '“' + String(n.content || '').replace(/\s+/g, ' ').slice(0, 30) + '”' : n.type;
    return text + ' · ' + n.id;
  }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }
  function opts(list, cur) { return list.map(function (v) { return '<option' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(v) + '</option>'; }).join(''); }
  function field(id, labelText, control) { return '<div class="ms-f"><label class="ms-label" for="' + id + '">' + labelText + '</label>' + control + '</div>'; }

  // ── inspector ────────────────────────────────────────────────────────────
  function inspector() {
    var h = q('#ms-inspector'), n = selected ? findNode(current, selected) : null;
    if (!n) { h.innerHTML = '<p class="ms-kicker">Selected layer</p><p class="ms-muted">Click a layer on the frame or in the list. Drag to move it; the inspector edits its pose, its glass material and its text. Every change is previewed through the same renderer that exports.</p>'; return; }
    var e = edits.get(current + '/' + n.id) || {dx: 0, dy: 0, scale: 1, rotation: 0};
    var html = '<p class="ms-kicker">Selected layer</p><p class="ms-muted">' + esc(label(n)) + (n.continuity_key ? ' · <b style="color:#ffb3bd">thread “' + esc(n.continuity_key) + '”</b>' : '') + '</p>';
    if (n.type === 'text') html += field('ms-text', 'Text', '<input class="ms-field" id="ms-text" value="' + esc(typeof e.text === 'string' ? e.text : (n.content || '')) + '">');
    html += '<div class="ms-row">' + field('ms-x', 'Move X', '<input class="ms-field" id="ms-x" type="number" value="' + (e.dx || 0) + '">')
      + field('ms-y', 'Move Y', '<input class="ms-field" id="ms-y" type="number" value="' + (e.dy || 0) + '">') + '</div>';
    html += '<div class="ms-row">' + field('ms-scale', 'Scale ×', '<input class="ms-field" id="ms-scale" type="number" step=".05" min=".05" max="20" value="' + (e.scale || 1) + '">')
      + field('ms-rot', 'Rotate °', '<input class="ms-field" id="ms-rot" type="number" step="1" value="' + (e.rotation || 0) + '">') + '</div>';
    html += field('ms-opacity', 'Opacity', '<input class="ms-range" id="ms-opacity" type="range" min="0" max="1" step=".05" value="' + (e.opacity != null ? e.opacity : (n.opacity != null ? n.opacity : 1)) + '">');
    if (n.type === 'glass_panel') {
      var m = e.material || {};
      function mat(k, labelText, max) { var v = m[k] != null ? m[k] : (n[k] != null ? n[k] : ''); return field('ms-m-' + k, labelText, '<input class="ms-range" data-mat="' + k + '" id="ms-m-' + k + '" type="range" min="0" max="' + max + '" step="' + (max > 1 ? 1 : 0.05) + '" value="' + (v === '' ? (k === 'blur' ? 18 : 0.5) : v) + '">'); }
      html += '<p class="ms-kicker" style="margin-top:8px">Glass material</p>' + mat('blur', 'Blur (px)', 40) + '<div class="ms-row">' + mat('transmission', 'Transmission', 1) + mat('border_light', 'Edge light', 1) + '</div><div class="ms-row">' + mat('inner_shadow', 'Inner shadow', 1) + mat('specular', 'Specular', 1) + '</div>';
    }
    html += '<div class="ms-row"><button class="ms-btn" id="ms-hide">' + (e.hidden ? 'Show layer' : 'Hide layer') + '</button><button class="ms-btn" id="ms-reset" title="Back to how the design had it">Reset</button></div>';
    h.innerHTML = html;
    h.querySelectorAll('input,select').forEach(function (c) { c.addEventListener('focus', saveState); });
    function on(id, ev, fn) { var c = q('#' + id); if (c) c.addEventListener(ev, function () { var r = nodeRecord(current, n.id); fn(r, this.value); preview(); }); }
    on('ms-text', 'input', function (r, v) { r.text = v; });
    on('ms-x', 'input', function (r, v) { r.dx = +v || 0; });
    on('ms-y', 'input', function (r, v) { r.dy = +v || 0; });
    on('ms-scale', 'input', function (r, v) { r.scale = Math.min(20, Math.max(0.05, +v || 1)); });
    on('ms-rot', 'input', function (r, v) { r.rotation = +v || 0; });
    on('ms-opacity', 'input', function (r, v) { r.opacity = +v; });
    h.querySelectorAll('input[data-mat]').forEach(function (c) {
      c.addEventListener('input', function () { var r = nodeRecord(current, n.id); r.material = r.material || {}; r.material[this.dataset.mat] = +this.value; preview(); });
    });
    q('#ms-hide').onclick = function () { saveState(); var r = nodeRecord(current, n.id); r.hidden = !r.hidden; preview(true); inspector(); };
    q('#ms-reset').onclick = function () { saveState(); edits.delete(current + '/' + n.id); preview(true); inspector(); };
  }

  // ── scene: length, shot, handoff ─────────────────────────────────────────
  function sceneUI() {
    var src = sourceScene(current), res = scenes()[current] || {}, e = edits.get(current + '/root') || {};
    var shot = e.shot || src.shot || {intent: 'hold'};
    q('#ms-seconds').value = e.seconds || src.duration || res.duration || 3;
    q('#ms-shot').innerHTML = opts(SHOTS, shot.intent || 'hold');
    q('#ms-target').value = typeof shot.target === 'string' ? shot.target : (Array.isArray(shot.target) ? shot.target.join(',') : '');
    q('#ms-zoom').value = shot.zoom != null ? shot.zoom : '';
    var easing = e.handoff_easing || src.handoff_easing || 'power2.inOut';
    q('#ms-easing').innerHTML = opts(EASINGS.indexOf(easing) === -1 ? [easing].concat(EASINGS) : EASINGS, easing);
    q('#ms-easing').disabled = current === 0;
    q('#ms-cut').textContent = current === 0 ? 'The first scene has no cut into it.' : 'Cut into this scene: ' + (res.transition_in || 'auto') + (res.transition_in === 'morph' ? ' — the carried subject is bridged.' : '.');
  }
  function shotFromUI() {
    var target = q('#ms-target').value.trim(), shot = {intent: q('#ms-shot').value};
    if (target) { var pair = target.split(',').map(Number); shot.target = pair.length === 2 && pair.every(function (v) { return !isNaN(v); }) ? pair : target; }
    var z = parseFloat(q('#ms-zoom').value); if (!isNaN(z)) shot.zoom = z;
    return shot;
  }
  function diagnostics() {
    var h = q('#ms-diag'), html = '';
    (PREVIEW.errors || []).forEach(function (m) { html += '<p class="ms-diag err">' + esc(m) + '</p>'; });
    (PREVIEW.warnings || []).forEach(function (m) { html += '<p class="ms-diag warn">' + esc(m) + '</p>'; });
    h.innerHTML = html || '<p class="ms-diag ok">Every handoff bridges and the camera curve is continuous.</p>';
  }

  // ── lists ────────────────────────────────────────────────────────────────
  function scenesList() {
    var h = q('#ms-scenes'); h.innerHTML = '';
    scenes().forEach(function (s, i) {
      var src = sourceScene(i), shot = ((edits.get(i + '/root') || {}).shot || src.shot || {}).intent || 'hold';
      var b = document.createElement('button'); b.className = 'ms-card ' + (i === current ? 'active' : '');
      b.innerHTML = '<i class="ms-thumb"></i><span><strong>Scene ' + (i + 1) + '</strong><small>' + fmt(s.duration || 0) + ' · ' + esc(shot) + (i ? ' · ' + esc(s.transition_in || 'cut') : '') + '</small></span>';
      b.onclick = function () { showScene(i); }; h.appendChild(b);
    });
  }
  function threadList() {
    var h = q('#ms-threads'); h.innerHTML = '';
    var th = threads(), keys = Object.keys(th);
    if (!keys.length) { h.innerHTML = '<p class="ms-muted">No continuity thread yet — give the carried subject a continuity_key and it will show here.</p>'; return; }
    keys.forEach(function (k) {
      var d = document.createElement('div'); d.className = 'ms-thread ' + (k === activeThread ? 'active' : '');
      d.innerHTML = '<b>' + esc(k) + '</b><small>' + th[k].map(function (it) { return 'scene ' + (it.scene_index + 1) + ' · ' + esc(it.node); }).join(' → ') + '</small>';
      d.onclick = function () {
        activeThread = activeThread === k ? null : k;
        var here = th[k].filter(function (it) { return it.scene_index === current; })[0] || th[k][0];
        if (activeThread && here) { if (here.scene_index !== current) showScene(here.scene_index); pick(here.node); } else highlight();
        threadList();
      };
      h.appendChild(d);
    });
  }
  function layers() {
    var h = q('#ms-layers'); if (!h) return; h.innerHTML = '';
    walk(sourceScene(current).nodes, function (n, depth) {
      var b = document.createElement('button'); b.className = 'ms-row-btn ' + (String(n.id) === String(selected) ? 'active' : '');
      b.style.paddingLeft = (7 + depth * 14) + 'px';
      b.innerHTML = '<i class="ms-dot' + (n.continuity_key ? ' key' : '') + '"></i><span>' + esc(label(n)) + '</span>';
      b.onclick = function () { pick(n.id); }; h.appendChild(b);
    });
  }
  function timeline() {
    var h = q('#ms-timeline'); h.innerHTML = '';
    var tracks = ((resolved().camera || {}).tracks) || [], tot = Math.max(0.001, total());
    beatTicks(h, tot);
    scenes().forEach(function (s, i) {
      var b = document.createElement('button'); b.className = 'ms-block ' + (i === current ? 'active' : '');
      b.style.flex = Math.max(0.2, s.duration || 0);
      var cam = tracks.filter(function (t) { return t._shot && t._shot !== 'open' && Math.abs((t.time || 0) - (s.start || 0)) < 0.01; })[0];
      var keys = []; walk(sourceScene(i).nodes, function (n) { if (n.continuity_key && keys.indexOf(n.continuity_key) === -1) keys.push(n.continuity_key); });
      b.innerHTML = '<span>' + (i + 1) + ' · ' + fmt(s.duration || 0) + '</span>'
        + (cam ? '<span class="cam">camera ' + esc(cam._shot) + ' → zoom ' + cam.zoom + '</span>' : '<span class="cam">camera holds</span>')
        + (keys.length ? '<span class="thread">thread: ' + esc(keys.join(', ')) + '</span>' : '');
      b.onclick = function () { showScene(i); }; h.appendChild(b);
      if (i > 0) {
        var handle = document.createElement('i'); handle.className = 'ms-handle' + ((PREVIEW.errors || []).length ? ' broken' : ''); handle.title = 'Handoff into scene ' + (i + 1) + (s.transition_in ? ' · ' + s.transition_in : '') + ' — click to scrub the cut';
        handle.style.left = (100 * (s.start || 0) / tot) + '%';
        handle.onclick = function (ev) { ev.stopPropagation(); current = i; seek(Math.max(0, (s.transitionInStart != null ? s.transitionInStart : s.start))); refresh(); };
        h.appendChild(handle);
      }
    });
  }
  function beatTicks(h, tot) {
    var grid = PREVIEW.beats || {}, beats = grid.beats || [], bars = grid.bars || [];
    if (!beats.length || beats.length > 600) return;
    beats.forEach(function (t) {
      var tick = document.createElement('i'); tick.className = 'ms-beat' + (bars.indexOf(t) !== -1 ? ' bar' : '');
      tick.style.left = (100 * t / tot) + '%'; tick.title = t.toFixed(2) + 's · ' + grid.bpm + ' bpm'; h.appendChild(tick);
    });
    (grid.markers || []).forEach(function (m) {
      if (m.kind !== 'cut' || m.on_beat) return;
      var off = document.createElement('i'); off.className = 'ms-offbeat'; off.style.left = (100 * m.time / tot) + '%';
      off.title = m.label + ' is ' + Math.round(Math.abs(m.drift) * 1000) + 'ms off the beat'; h.appendChild(off);
    });
    var tag = q('#ms-beat-tag'); if (tag) tag.textContent = grid.bpm ? grid.bpm + ' bpm (' + grid.source + ')' : '';
  }

  function refresh() { scenesList(); threadList(); layers(); inspector(); timeline(); sceneUI(); diagnostics(); fit(); buttons(); seek(time); }

  // ── chrome ───────────────────────────────────────────────────────────────
  var top = document.createElement('header'); top.id = 'motion-top';
  top.innerHTML = '<span class="brand">Prism <i>Motion Studio</i></span>'
    + '<button class="ms-btn" id="ms-play">▶ Play</button>'
    + '<button class="ms-btn" id="ms-undo">Undo</button><button class="ms-btn" id="ms-redo">Redo</button>'
    + '<button class="ms-btn" id="ms-safe" title="Show the 9:16 platform bands and the title/action zones">Safe area</button>'
    + '<span class="ms-spacer"></span>'
    + '<button class="ms-btn" id="ms-zoom-out">−</button><button class="ms-btn" id="ms-zoom-in">+</button>'
    + '<span class="ms-status" id="ms-status">Ready</span>'
    + '<button class="ms-btn" id="ms-save">Save</button>'
    + '<button class="ms-btn primary" id="ms-render">Render MP4</button>';
  document.body.appendChild(top);
  var left = document.createElement('aside'); left.id = 'motion-left';
  left.innerHTML = '<section class="ms-section"><p class="ms-kicker">Scenes</p><div id="ms-scenes"></div></section>'
    + '<section class="ms-section"><p class="ms-kicker">Continuity threads</p><div id="ms-threads"></div></section>'
    + '<section class="ms-section"><p class="ms-kicker">Layers</p><div id="ms-layers"></div></section>';
  document.body.appendChild(left);
  var right = document.createElement('aside'); right.id = 'motion-right';
  right.innerHTML = '<section class="ms-section"><div id="ms-inspector"></div></section>'
    + '<section class="ms-section"><p class="ms-kicker">This scene</p>'
    + '<div class="ms-row">' + field('ms-seconds', 'Length (s)', '<input class="ms-field" id="ms-seconds" type="number" min="0.5" max="30" step="0.5">') + '</div>'
    + '<div class="ms-row">' + field('ms-shot', 'Camera shot', '<select class="ms-field" id="ms-shot"></select>')
    + field('ms-zoom', 'Zoom', '<input class="ms-field" id="ms-zoom" type="number" min="0.5" max="3" step="0.05" placeholder="auto">') + '</div>'
    + field('ms-target', 'Looks at (node id or x,y)', '<input class="ms-field" id="ms-target" placeholder="the subject">')
    + field('ms-easing', 'Handoff easing (cut into this scene)', '<select class="ms-field" id="ms-easing"></select>')
    + '<p class="ms-muted" id="ms-cut"></p></section>'
    + '<section class="ms-section"><p class="ms-kicker">Continuity check</p><div id="ms-diag"></div></section>';
  document.body.appendChild(right);
  var bottom = document.createElement('footer'); bottom.id = 'motion-bottom';
  bottom.innerHTML = '<div class="ms-transport"><button class="ms-btn" id="ms-play-2">▶</button><span class="ms-time" id="ms-time"></span>'
    + '<input class="ms-range" id="ms-scrub" type="range" min="0" step="0.01"><span class="ms-spacer"></span><span class="ms-muted" id="ms-beat-tag"></span><span class="ms-muted">Camera · threads · handoffs · beats</span></div>'
    + '<div class="ms-timeline" id="ms-timeline"></div>'
    + '<div class="ms-review"><span class="ms-muted">Review this shot:</span>'
    + '<button class="ms-btn" data-review="start">Start</button><button class="ms-btn" data-review="mid">Midpoint</button>'
    + '<button class="ms-btn" data-review="settled">Settled</button><button class="ms-btn" data-review="exit">Exit</button></div>'
    + '<div class="ms-prompt"><input class="ms-field" id="ms-prompt" placeholder="Describe a change to the selected layer, thread or scene…"><button class="ms-btn primary" id="ms-refine">Refine</button></div>'
    + '<div class="ms-help">Space play/pause · Ctrl/⌘ Z undo · arrows nudge · Shift arrows 10px · +/- zoom · Esc deselect</div>';
  document.body.appendChild(bottom);

  // ── wiring ───────────────────────────────────────────────────────────────
  q('#ms-scrub').max = total(); q('#ms-scrub').oninput = function () { seek(+this.value); };
  q('#ms-play').onclick = toggle; q('#ms-play-2').onclick = toggle;
  q('#ms-save').onclick = function () { post('/save', null, function (ok) { status(ok ? 'Saved' : 'Save failed'); dirty = !ok; }); };
  q('#ms-render').onclick = function () { post('/render', null, function (ok) { status(ok ? 'Rendering…' : 'Render failed'); }); };
  q('#ms-undo').onclick = function () { if (undo.length) { redo.push(JSON.stringify(all())); restore(undo.pop()); buttons(); } };
  q('#ms-redo').onclick = function () { if (redo.length) { undo.push(JSON.stringify(all())); restore(redo.pop()); buttons(); } };
  q('#ms-safe').onclick = function () { safe.classList.toggle('on'); this.classList.toggle('active', safe.classList.contains('on')); };
  q('#ms-zoom-in').onclick = function () { zoom = Math.min(2, zoom + .1); fit(); };
  q('#ms-zoom-out').onclick = function () { zoom = Math.max(.25, zoom - .1); fit(); };
  document.querySelectorAll('[data-review]').forEach(function (b) { b.onclick = function () { showScene(current, b.dataset.review); }; });

  ['ms-seconds', 'ms-shot', 'ms-zoom', 'ms-target', 'ms-easing'].forEach(function (id) { q('#' + id).addEventListener('focus', saveState); });
  q('#ms-seconds').addEventListener('change', function () { var v = +this.value; if (v >= 0.5 && v <= 30) { sceneRecord(current).seconds = v; preview(true); } });
  ['ms-shot', 'ms-zoom', 'ms-target'].forEach(function (id) { q('#' + id).addEventListener('change', function () { sceneRecord(current).shot = shotFromUI(); preview(true); }); });
  q('#ms-easing').addEventListener('change', function () { sceneRecord(current).handoff_easing = this.value; preview(true); });

  q('#ms-refine').onclick = function () {
    var change = q('#ms-prompt').value.trim(); if (!change) return;
    var n = selected ? findNode(current, selected) : null;
    post('/refine', {change: change, context: {scene_index: current, scene_id: (sourceScene(current).id || ''), node_id: selected || '',
      continuity_key: activeThread || (n && n.continuity_key) || '', label: n ? label(n) : 'scene'}},
      function (ok) { status(ok ? 'Follow-up started — this window can be closed' : 'Follow-up unavailable'); if (ok) q('#ms-prompt').value = ''; });
  };

  // Click selects, drag moves (dx/dy on the record; the runtime is reloaded on release).
  stage.addEventListener('mousedown', function (event) {
    var host = event.target.closest('[data-motion-id]'); if (!host) return;
    event.preventDefault();
    var id = host.dataset.motionId; pick(id); saveState();
    drag = {x: event.clientX, y: event.clientY, id: id, moved: false, box: host.firstElementChild};
  });
  addEventListener('mousemove', function (event) {
    if (!drag) return;
    var dx = (event.clientX - drag.x) / (base * zoom), dy = (event.clientY - drag.y) / (base * zoom);
    if (!dx && !dy) return;
    var r = nodeRecord(current, drag.id);
    r.dx = Math.round((r.dx || 0) + dx); r.dy = Math.round((r.dy || 0) + dy);
    drag.x = event.clientX; drag.y = event.clientY; drag.moved = true;
    if (drag.box) drag.box.style.translate = ((drag.box._tx = (drag.box._tx || 0) + dx)) + 'px ' + ((drag.box._ty = (drag.box._ty || 0) + dy)) + 'px';
  });
  addEventListener('mouseup', function () { if (drag) { var moved = drag.moved; drag = null; if (moved) { preview(true); inspector(); } } });
  addEventListener('keydown', function (event) {
    if (/INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName)) return;
    var k = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && k === 'z') { event.preventDefault(); q(event.shiftKey ? '#ms-redo' : '#ms-undo').click(); }
    else if (event.key === ' ') { event.preventDefault(); toggle(); }
    else if (selected && /^Arrow/.test(event.key)) {
      event.preventDefault(); saveState();
      var r = nodeRecord(current, selected), n = event.shiftKey ? 10 : 1;
      r.dx = (r.dx || 0) + (event.key === 'ArrowRight' ? n : event.key === 'ArrowLeft' ? -n : 0);
      r.dy = (r.dy || 0) + (event.key === 'ArrowDown' ? n : event.key === 'ArrowUp' ? -n : 0);
      preview(); inspector();
    }
    else if (event.key === '+' || event.key === '=') q('#ms-zoom-in').click();
    else if (event.key === '-') q('#ms-zoom-out').click();
    else if (event.key === 'Escape') { activeThread = null; pick(null); threadList(); }
  });
  addEventListener('resize', fit);
  addEventListener('beforeunload', function () { if (dirty) navigator.sendBeacon('/autosave', new Blob([JSON.stringify({edits: all()})], {type: 'application/json'})); });

  window.__motionStudio = {edits: all, select: pick, showScene: showScene, threads: threads, state: function () { return {current: current, selected: selected, time: time, thread: activeThread}; }};
  runtime.loadSpec(JSON.parse(JSON.stringify(resolved())));
  showScene(0);
})();
