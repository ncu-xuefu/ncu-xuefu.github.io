/* 09-app.js -- XF.app: the state machine (gate -> intro -> transition -> wishScene -> compose ->
   handoff -> wallModal -> wall), the hard timeouts, and all wiring.
   First principle (计划书 §3.3): the animation may break; writing a blessing may not. */
(function (w, d) {
  'use strict';
  var XF = w.XF;
  var $ = function (id) { return d.getElementById(id); };

  XF.app = {
    state: 'gate', timers: {}, introDone: false, submitted: null, wishAuto: false,

    TIMEOUT: { intro: 12000, transition: 6000, wishScene: 12000, handoff: 15000 },

    advance: function (next) {
      // One line cuts every posting path in a snapshot: `compose` is the only state that can reach
      // submit, and the wishScene timer, 跳过 and the wall's 再写一条祝福 all funnel through here.
      if (XF.cfg.snapshot && next === 'compose') next = 'wall';
      if (this.state === next && next !== 'intro') return;
      clearTimeout(this.timers[this.state]);
      clearTimeout(this.timers[next]);
      this.state = next;
      XF.ui.showScene(next);
      var self = this;

      if (next === 'intro') {
        this.introDone = false;
        XF.fx.playIntro(
          function () { self.advance('transition'); },
          function () { if (!self.introDone) { self.introDone = true; self.advance('wishScene'); } }
        );
      } else if (next === 'transition') {
        XF.fx.playGround();
        XF.fx.playWish();
        if (XF.audio) XF.audio.crackle(true);
      } else if (next === 'wishScene') {
        // BOTH the show's own rhythm (计划书 §3.2: wishScene ≈ 6 s) and the 12 s net are
        // first-pass only. A visitor who walks back from the wall to look at the characters must not
        // be pushed into the compose dialog by either of them.
        if (XF.cfg.snapshot || !this.wishAuto) {
          this.wishAuto = true;
          setTimeout(function () {
            if (self.state === 'wishScene') self.advance('compose');
          }, XF.cfg.lite ? 700 : 6000);
          this.arm('wishScene');
        }
      } else if (next === 'compose') {
        if (XF.audio) XF.audio.crackle(false);
        XF.ui.setCount(XF.util.codepoints($('compose-input').value || ''));
      } else if (next === 'handoff') {
        if (XF.audio) XF.audio.crackle(false);
        XF.fx.playHandoff(function () { self.advance('wallModal'); });
        this.arm('handoff');
      } else if (next === 'wallModal') {
        XF.data.startPolling();
        XF.ui.openWallModal();
      } else if (next === 'wall') {
        XF.data.startPolling();
        if (!XF.cfg.snapshot) XF.admin.armEntry();   // no server behind a snapshot: deletes cannot work
        XF.wall.start();
        if (this.submitted) self.showShare(this.submitted);
      }
      // wishScene armed its own net above, and only on the first pass
      if (this.TIMEOUT[next] && next !== 'wishScene') this.arm(next);
    },

    arm: function (state) {
      var self = this;
      clearTimeout(this.timers[state]);
      var t = this.TIMEOUT[state];
      if (!t) return;
      this.timers[state] = setTimeout(function () {
        // Only the handoff timeout is a network symptom worth a toast; a scene timeout means an
        // animation stalled, and 「小服正在努力接上…」 would blame the visitor's network (review minor 13).
        if (state === 'handoff') { XF.ui.toastOnce(XF.copy.offline); self.advance('wallModal'); return; }
        XF.fx.cancelIntro();
        XF.fx.wishSettle();
        self.advance('compose');
      }, t);
    },

    // 跳过只跳「看」，不跳「演出」: the handoff still plays after submitting (E27)
    skip: function () {
      if (this.state === 'compose' || this.state === 'handoff' || this.state === 'wall' || this.state === 'wallModal') return;
      this.introDone = true;
      // Mark the show as consumed: without this, coming back from the wall via 回到许愿场 re-arms the
      // 6 s auto-advance and the visitor is thrown into compose mid-look (review I2).
      this.wishAuto = true;
      XF.fx.cancelIntro();
      XF.ui.showScene('wishScene');
      XF.fx.wishSettle();
      this.advance('compose');
    },

    // Start the card the moment the POST returns: the handoff still plays for ~4.2 s, so by the time
    // the visitor reaches the wall the server image is usually already there and long-press works on
    // the first try (a blob: image cannot be saved by WeChat at all -- see 07-share.js).
    prepareShare: function (wish) {
      if (XF.cfg.bare || !XF.share || !wish) return null;
      this.submitted = wish;
      var self = this;
      this._shareNet = '';
      this._sharePromise = XF.share.make(wish, function (netUrl) {
        self._shareNet = netUrl || '';
        if (netUrl) XF.ui.setShareSrc(netUrl);        // swap blob -> server URL (saveable)
        if (self.state === 'wall' || self.state === 'wallModal') XF.ui.setShareState(netUrl ? 'ready' : 'failed');
      });
      return this._sharePromise;
    },

    showShare: function (wish) {
      if (XF.cfg.bare || !XF.share || !wish) return;
      var self = this;
      var pr = this._sharePromise || this.prepareShare(wish);
      if (!pr) return;
      pr.then(function (res) {
        if (!res) return;
        var url = self._shareNet || res.netUrl || res.blobUrl;   // prefer the saveable one
        if (url) XF.ui.showShare(url, self._shareNet ? 'ready' : (res.uploadFailed ? 'failed' : 'preparing'));
      });
    },

    submit: function () {
      var input = $('compose-input');
      var raw = XF.util.sanitize(input.value || '');   // same invisible-character rule as the server
      if (raw !== input.value) input.value = raw;
      var text = raw.trim().replace(/\n{4,}/g, '\n\n\n');
      var n = XF.util.codepoints(text);
      if (n === 0) { XF.ui.toast(XF.copy.errGeneric); return; }
      if (n > XF.cfg.limits.textMax) { XF.ui.toast(XF.copy.errTooLong); return; }
      XF.ui.hideShare();
      XF.data.submit(text).then(function () {
        // handoff advances the state machine; find our own wish and start its card NOW, during the
        // handoff animation, so the upload is done before anyone can long-press
        var mine = XF.data.mine;
        for (var i = XF.data.wishes.length - 1; i >= 0; i--) {
          if (mine.indexOf(XF.data.wishes[i].id) >= 0) { XF.app.prepareShare(XF.data.wishes[i]); break; }
        }
      });
    },

    boot: function () {
      // Snapshot build (tools/snapshot.mjs) -- a server-less copy of this page for GitHub Pages.
      // The exporter injects this meta into the copied index.html; from here on the ONLY difference
      // is where the data comes from and that there is no way to post. The show is byte-identical.
      XF.cfg.snapshot = !!d.querySelector('meta[name="xf-snapshot"]');
      XF.cfg.lite = /[?&]lite=1/.test(w.location.search);
      XF.cfg.bare = /[?&]bare=1/.test(w.location.search);
      if (XF.cfg.bare) XF.cfg.lite = true;
      if ((XF.cfg.lite || XF.cfg.bare) && d.body) d.body.classList.add('lite');

      XF.data.init();
      XF.wall.init().start();      // .els must exist before any render(); the loop is harmless while empty
      XF.ui.initSky();
      XF.ui.installKeyboard();
      XF.fx.applyHatGeometry();
      XF.audio.init();
      XF.confetti.init();

      // ── wiring ──
      $('scene-gate').addEventListener('click', function () {
        XF.audio.unlock();                       // the one legal moment to create an AudioContext
        XF.fx.preloadSprites();
        if (XF.cfg.bare) return;
        XF.app.advance('intro');
        setTimeout(function () { XF.ui.skipArmed = true; XF.ui.setTopUi(XF.app.state); }, 1200);
      });
      $('btn-skip').addEventListener('click', function () { XF.app.skip(); });

      var input = $('compose-input');
      var cleanAndCount = function () {
        var v = input.value || '';
        var c = XF.util.sanitize(v);
        if (c !== v) { input.value = c; v = c; }        // silent: the removed characters were invisible
        var n = XF.util.codepoints(v);
        XF.ui.setCount(n);
        $('compose-submit').disabled = n === 0 || n > XF.cfg.limits.textMax;
        return v;
      };
      input.addEventListener('input', cleanAndCount);
      input.addEventListener('paste', function () {
        setTimeout(function () {
          var max = XF.cfg.limits.textMax;
          var v = cleanAndCount();
          if (XF.util.codepoints(v) > max) {            // truncate by CODEPOINT, never mid-surrogate
            input.value = XF.util.cpSlice(v, max);
            XF.ui.setCount(max);
          }
        }, 0);
      });
      $('compose-submit').addEventListener('click', function () { XF.app.submit(); });
      $('compose-name').addEventListener('input', function () {
        var el = $('compose-name'), max = XF.cfg.limits.nameMax;
        var c = XF.util.sanitize(el.value || '');
        if (XF.util.codepoints(c) > max) c = XF.util.cpSlice(c, max);
        if (c !== el.value) el.value = c;
      });

      $('btn-wall-go').addEventListener('click', function () {
        XF.ui.closeWallModal();
        XF.app.advance('wall');
      });
      $('btn-pause-close').addEventListener('click', function () { XF.wall.resume(); });
      $('btn-pause-delete').addEventListener('click', function () {
        var id = Number($('pause-card').getAttribute('data-id') || 0);
        if (id) XF.admin.remove(id);
      });
      $('btn-write-more').addEventListener('click', function () {
        XF.ui.hideShare();
        input.value = '';
        XF.ui.setCount(0);
        XF.app.advance('compose');
      });
      // …and in a snapshot the button itself goes away: advance() would route it to the wall anyway,
      // but a control that silently does nothing is worse than no control.
      if (XF.cfg.snapshot) { $('btn-write-more').hidden = true; }
      $('btn-back-wish').addEventListener('click', function () {
        XF.fx.resetWishStage();
        XF.ui.hideShare();
        XF.app.advance('wishScene');
      });
      $('share-close').addEventListener('click', function () { XF.ui.hideShare(); });

      $('btn-admin-ok').addEventListener('click', function () { XF.admin.login(); });
      $('btn-admin-close').addEventListener('click', function () { XF.ui.closeAdmin(); });
      $('btn-admin-freeze').addEventListener('click', function () { XF.admin.setState(false); });
      $('btn-admin-thaw').addEventListener('click', function () { XF.admin.setState(true); });
      $('btn-undo').addEventListener('click', function () { XF.admin.undo(); });

      // the pause card remembers which wish it shows, so the delete button knows its target
      var origOpenPause = XF.ui.openPause;
      XF.ui.openPause = function (wish) {
        $('pause-card').setAttribute('data-id', String(wish.id));
        XF.admin.syncDeleteButton();
        return origOpenPause.call(XF.ui, wish);
      };

      // ── config then first screen ──
      // ?bare=1 must not show the gate for one config round-trip (review minor 13)
      if (XF.cfg.bare) { XF.ui.setTopUi('compose'); XF.app.advance('compose'); }
      XF.util.fetchConfig().then(function () {
        if (!XF.cfg.bare) XF.ui.showScene('gate');
      });
      XF.data.loadInitial();
    }
  };

  if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', function () { XF.app.boot(); });
  else XF.app.boot();
})(window, document);
