/* 02-ui.js -- XF.ui: scene switching, modals, toast, keyboard offset, ambient decoration.
   Scene visibility is ALWAYS opacity/visibility (E29): a display:none ancestor would freeze the
   confetti and the rAF star stream, which on stage looks exactly like "the animation stopped". */
(function (w, d) {
  'use strict';
  var XF = w.XF;
  var SCENES = ['scene-gate', 'scene-intro', 'scene-wish', 'scene-compose', 'scene-wall'];
  // state -> which scenes stay lit. compose keeps the wish stage behind the dialog on purpose
  // (计划书 §3.2: 输入期间背景动画不停).
  var LIT = {
    gate: ['scene-gate'], intro: ['scene-intro'], transition: ['scene-wish'], wishScene: ['scene-wish'],
    compose: ['scene-wish', 'scene-compose'], handoff: ['scene-wish'],
    // wallModal keeps the WISH scene lit: the plan lands the modal above the cake that was just
    // handed over (§7.4). The wall itself appears once the visitor taps 看看.
    wallModal: ['scene-wish'], wall: ['scene-wall']
  };
  var toastTimer = null, lastToast = { msg: '', at: 0 };

  XF.ui = {
    current: 'gate',

    showScene: function (state) {
      var want = LIT[state] || [];
      for (var i = 0; i < SCENES.length; i++) {
        var el = XF.util.$(SCENES[i]);
        if (!el) continue;
        var on = want.indexOf(SCENES[i]) >= 0;
        el.classList.toggle('off', !on);
        el.setAttribute('aria-hidden', on ? 'false' : 'true');
      }
      this.current = state;
      // the compose dialog slides up from the bottom, one frame after the scene un-hides
      var dlg = XF.util.$('compose-dialog');
      if (state === 'compose') {
        w.requestAnimationFrame(function () { dlg.classList.add('in'); });
        dlg.style.transition = 'transform .42s cubic-bezier(.2,.7,.3,1)';
      } else if (state === 'handoff') {
        dlg.style.transition = 'transform .4s ease-in';
        dlg.classList.remove('in');
      } else {
        dlg.classList.remove('in');
      }
      if (state === 'wall' || state === 'wallModal') { XF.ui.setTopUi('wall'); }
      else if (state === 'compose') XF.ui.setTopUi('compose');
      else if (state === 'gate') XF.ui.setTopUi('gate');
      else XF.ui.setTopUi('show');
    },

    // skip + sound. skip is 常驻 (计划书 §3.3) but arms 1.2 s after the gate tap; it is never
    // visible DURING gate. sound is inert during gate because E45 locks AudioContext creation
    // to the gate tap itself -- a live toggle there would be a control that cannot work.
    skipArmed: false,
    setTopUi: function (mode) {
      var skip = XF.util.$('btn-skip'), sound = XF.util.$('btn-sound');
      if (XF.cfg.bare) { skip.classList.add('off'); sound.classList.add('off'); return; }
      // 常驻 through the show, but the wall has its own reverse-navigation button -- a control that
      // does nothing on the screen where it appears is worse than no control (review minor 13).
      skip.classList.toggle('off', !(this.skipArmed && mode !== 'gate' && mode !== 'wall'));
      sound.classList.toggle('off', mode === 'gate');
      sound.classList.toggle('dead', mode === 'gate');
    },

    toast: function (msg) {
      if (!msg) return;
      var t = XF.util.$('toast');
      t.textContent = msg;
      t.classList.remove('off');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(function () { t.classList.add('off'); }, 2600);
    },
    toastOnce: function (msg) {
      var now = Date.now();
      if (lastToast.msg === msg && now - lastToast.at < 8000) return;
      lastToast = { msg: msg, at: now };
      XF.ui.toast(msg);
    },

    openWallModal: function () { XF.util.$('wall-modal').classList.remove('off'); },
    closeWallModal: function () { XF.util.$('wall-modal').classList.add('off'); },

    openPause: function (wish) {
      XF.util.$('pause-name').textContent = wish.name ? wish.name : XF.copy.anonymous;
      XF.util.$('pause-time').textContent = XF.util.fmtRelTime(wish.ts);
      XF.util.$('pause-text').textContent = wish.text;
      XF.util.$('pause-card').classList.remove('off');
      if (XF.audio) XF.audio.sfx('pop');
    },
    closePause: function () { XF.util.$('pause-card').classList.add('off'); },

    openAdmin: function () { XF.util.$('admin-modal').classList.remove('off'); XF.util.$('admin-token').focus(); },
    closeAdmin: function () { XF.util.$('admin-modal').classList.add('off'); },
    adminMsg: function (s) { XF.util.$('admin-msg').textContent = s || ''; },

    nameValue: function () {
      var v = XF.util.sanitize(XF.util.$('compose-name').value || '').trim();
      return XF.util.cpSlice(v, XF.cfg.limits.nameMax);
    },

    setCount: function (n) {
      var c = XF.util.$('compose-count');
      var max = XF.cfg.limits.textMax;
      c.textContent = XF.copy.count(n, max);
      c.classList.toggle('over', n > max);
    },

    // state: 'preparing' (blob only -- NOT saveable yet) | 'ready' | 'failed'
    showShare: function (url, state) {
      if (XF.cfg.bare) return;
      var wrap = XF.util.$('share-wrap');
      if (url) XF.util.$('share-img').setAttribute('src', url);
      XF.ui.setShareState(state || 'preparing');
      wrap.hidden = false;
      w.requestAnimationFrame(function () { wrap.classList.remove('off'); });
    },
    // Swap the <img> onto the server URL the moment it is confirmed loadable: only an http(s) image
    // gets a working long-press "save to album" in WeChat.
    setShareSrc: function (url) {
      var im = XF.util.$('share-img');
      if (im && url && im.getAttribute('src') !== url) im.setAttribute('src', url);
    },
    setShareState: function (state) {
      var hint = XF.util.$('share-hint');
      if (!hint) return;
      hint.textContent = state === 'ready' ? XF.copy.shareHint
        : (state === 'failed' ? XF.copy.shareFailed : XF.copy.sharePreparing);
      hint.classList.toggle('bad', state === 'failed');
    },
    shareSrc: function () { var i = XF.util.$('share-img'); return i ? (i.getAttribute('src') || '') : ''; },
    hideShare: function () {
      var wrap = XF.util.$('share-wrap');
      wrap.classList.add('off');
      setTimeout(function () { wrap.hidden = true; }, 300);
    },

    /* ── sky decoration: ~40 stars + ambient motes in the top 40% (计划书 §4.6) ── */
    initSky: function () {
      var box = XF.util.$('stars');
      if (!box || box.childElementCount) return;
      var frag = d.createDocumentFragment();
      for (var i = 0; i < 40; i++) {
        var s = d.createElement('i');
        s.style.left = (Math.random() * 100).toFixed(2) + '%';
        s.style.top = (Math.random() * 88).toFixed(2) + '%';
        var sz = (1.6 + Math.random() * 2.2).toFixed(1);
        s.style.width = sz + 'px'; s.style.height = sz + 'px';
        s.style.animationDelay = (-Math.random() * 4).toFixed(2) + 's';
        s.style.animationDuration = (3 + Math.random() * 2).toFixed(2) + 's';
        frag.appendChild(s);
      }
      box.appendChild(frag);
      var egg = XF.util.$('year-egg');
      if (egg) egg.textContent = XF.copy.yearEgg;
      var deco = XF.util.$('deco');
      if (deco) {
        var f2 = d.createDocumentFragment();
        for (var j = 0; j < 12; j++) {
          var m = d.createElement('i');
          var r = (2 + Math.random() * 4).toFixed(1);
          m.style.width = r + 'px'; m.style.height = r + 'px';
          m.style.left = (Math.random() * 96).toFixed(1) + '%';
          m.style.top = (Math.random() * 92).toFixed(1) + '%';
          f2.appendChild(m);
        }
        deco.appendChild(f2);
      }
    },

    /* ── keyboard (E33). iOS keeps innerHeight fixed; only visualViewport moves. ── */
    installKeyboard: function () {
      var vv = w.visualViewport;
      var stage = XF.util.$('stage');
      var apply = XF.util.rafThrottle(function () {
        var kbH = 0;
        if (vv) kbH = (w.innerHeight - vv.height - vv.offsetTop);
        kbH = XF.util.clamp(kbH || 0, 0, w.innerHeight * 0.6);
        if (kbH < 24) kbH = 0;
        stage.style.transform = 'translate3d(0,' + (-kbH) + 'px,0)';
        // typing lowers the confetti budget but NEVER pauses rAF or any CSS animation
        if (XF.confetti) XF.confetti.setDensity(kbH ? 25 : 80);
      });
      if (vv) { vv.addEventListener('resize', apply); vv.addEventListener('scroll', apply); }
      w.addEventListener('orientationchange', function () { setTimeout(apply, 250); });
    }
  };
})(window, document);
