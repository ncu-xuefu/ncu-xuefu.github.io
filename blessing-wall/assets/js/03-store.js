/* 03-store.js -- XF.data (local model, mine, optimistic insert, delta, polling) and XF.wall
   (the star stream). They live in one file on purpose: applying a delta and inserting into a
   track must happen in the same tick, or the two race (实现方案 §9).
   Rendering rules that keep the acceptance criterion "no card jumps":
     - cards are only ever APPENDED to the tail of a track, never inserted;
     - a track is recycled by moving its head to its tail, so total length never changes. */
(function (w, d) {
  'use strict';
  var XF = w.XF;
  var MINE_KEY = 'xf20.mine';

  XF.data = {
    wishes: [], ids: {}, mine: [], maxId: 0, delTs: 0, boot: '', backoff: 0,
    timer: null, polling: false,

    init: function () {
      var m = XF.util.store.get(MINE_KEY, []);
      this.mine = Object.prototype.toString.call(m) === '[object Array]' ? m : [];
    },
    isMine: function (id) { return this.mine.indexOf(id) >= 0; },
    rememberMine: function (id) {
      if (this.isMine(id)) return;
      this.mine.push(id);
      if (this.mine.length > 50) this.mine = this.mine.slice(-50);
      XF.util.store.set(MINE_KEY, this.mine);
    },

    applyOne: function (wish) {
      if (this.ids[wish.id]) return false;
      this.ids[wish.id] = wish;
      this.wishes.push(wish);
      if (wish.id > this.maxId) this.maxId = wish.id;
      return true;
    },

    loadInitial: function () {
      var self = this;
      // snapshot: the whole wall arrives as one baked file in the API's own shape, so every line
      // below -- including the "never silent" catch -- behaves exactly as it does against a server
      var url = XF.cfg.snapshot ? 'assets/data/wishes.json'
                                : ('/api/wishes?limit=' + XF.cfg.limits.wallPage);
      return fetch(url, { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j || !j.ok) return;
          self.wishes = []; self.ids = {}; self.maxId = 0;
          for (var i = 0; i < j.live.length; i++) self.applyOne(j.live[i]);
          self.maxId = Math.max(self.maxId, j.maxId || 0);
          // start the deletion cursor at the server's now: otherwise the first delta replays every
          // deletion ever made and can trip the reset rule (E10: >100 deletions -> full refetch)
          self.delTs = j.now || Date.now();
          self.boot = j.boot || '';
          XF.util.skew = (j.now || Date.now()) - Date.now();
          if (XF.wall) XF.wall.build();
        })
        .catch(function (e) {
          // Never silent: a swallowed error here is exactly the "wall just stops moving" family
          // of on-site failures (实现方案 §0.5). Submission must keep working regardless.
          if (w.console && console.warn) console.warn('[data] initial load failed:', e && e.message);
        });
    },

    reloadAll: function () {
      var self = this;
      if (XF.wall) XF.wall.resetDom();
      return self.loadInitial();
    },

    // A wish that arrives by polling must enter the stream, not just the model: the whole point of
    // the wall is that someone else's blessing shows up without a refresh. This is the one line
    // that makes the acceptance criterion true -- without it the wall silently freezes.
    applyDelta: function (j) {
      var i, added = 0;
      for (i = 0; i < (j.live || []).length; i++) {
        var w = j.live[i];
        if (!this.applyOne(w)) continue;
        added++;
        if (XF.wall) XF.wall.pushWish(w);
        if (XF.audio && XF.audio.sfx) XF.audio.sfx('shimmer');
      }
      if (added && XF.wall) XF.wall.render();
      for (i = 0; i < (j.deleted || []).length; i++) {
        var id = j.deleted[i];
        if (!this.ids[id]) continue;
        delete this.ids[id];
        for (var k = 0; k < this.wishes.length; k++) if (this.wishes[k].id === id) { this.wishes.splice(k, 1); break; }
        if (XF.wall) XF.wall.removeCard(id);      // a removal applies at once, never queued as new
      }
      // Do NOT adopt j.maxId as the cursor: it is the max id of the WHOLE live set, not of the page
      // just delivered. Adopting it skips the tail of any burst larger than `limit`, and the hasMore
      // retry then finds nothing -- those blessings are never shown on any wall that was already
      // open. applyOne already advances maxId to the page max, and a page is the first `limit` ids
      // above the cursor (contiguous, ascending), so the cursor is exactly right without this line.
      this.delTs = j.now || this.delTs;
      return added;
    },

    addMine: function (wish) {
      if (this.applyOne(wish)) this.rememberMine(wish.id);
      if (XF.wall) { XF.wall.pushWish(wish); XF.wall.render(); }
    },

    /* ── submit (实现方案 §8.2) ── */
    submit: function (text) {
      var btn = XF.util.$('compose-submit');
      btn.disabled = true;
      var body = { text: text, name: XF.ui.nameValue(), clientId: XF.util.clientId() };   // E41
      return fetch('/api/wishes', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      })
        .then(function (r) { return r.json().then(function (j) { return { status: r.status, j: j }; }); })
        .then(function (res) {
          var j = res.j || {};
          if (!j.ok) { XF.ui.toast(j.msg || XF.copy.errGeneric); btn.disabled = false; return; }
          XF.data.addMine(j.wish);
          if (XF.audio) XF.audio.sfx('ding');
          // through the state machine, not straight into the animation: advance('handoff') is what
          // slides the dialog away and arms the 15 s net (实现方案 §5.2/§7.4)
          XF.app.advance('handoff');
          w.setTimeout(function () { btn.disabled = false; }, 400);
        })
        .catch(function (e) {
          // Never silent: anything thrown after a successful POST would otherwise look like
          // "the submit did nothing" with a clean console (实现方案 §0.5 family).
          if (w.console && console.warn) console.warn('[submit]', e && e.stack ? e.stack : e);
          XF.ui.toast(XF.copy.offline); btn.disabled = false;
        });
    },

    /* ── polling (E21 / E37) ── */
    schedule: function (ms) {
      var self = this;
      if (!this.polling) return;
      clearTimeout(this.timer);
      this.timer = setTimeout(function () { self.tick(); }, Math.max(0, ms));
    },
    tick: function () {
      var self = this;
      this.timer = null;
      var t0 = Date.now();
      // The next poll is scheduled from the START of this one, not from its completion: with the
      // response latency added on top the period drifts to ~2.8-3.0 s, which eats the margin the
      // 3 s "visible without refreshing" criterion needs (E37 chose 2500 ms to leave exactly that).
      var period = function () { return Math.max(200, XF.cfg.pollMs - (Date.now() - t0)); };
      fetch('/api/wishes?since=' + this.maxId + '&delsince=' + this.delTs + '&limit=50', { cache: 'no-store' })
        .then(function (r) {
          if (r.status === 429) {
            return r.json().then(function (j) {
              XF.ui.toastOnce(XF.copy.offline);
              self.schedule((j.retryAfter || 12) * 1000);
            });
          }
          if (!r.ok) throw new Error('http ' + r.status);
          return r.json().then(function (j) {
            XF.util.skew = (j.now || Date.now()) - Date.now();
            // E21: the server moved backwards (a restart onto a smaller or empty db), so our cursor
            // is past anything it will ever send again and the wall would freeze for good. Compare
            // the cursor with the server's current max, and KEEP POLLING after the refetch -- the
            // refetch alone leaves the loop stopped until the page is backgrounded (review I1).
            if (j.boot !== self.boot && (j.maxId || 0) < self.maxId) {
              return self.reloadAll().then(function () {
                self.backoff = 0;
                self.schedule(XF.cfg.pollMs);
              });
            }
            self.boot = j.boot;
            self.applyDelta(j);
            XF.wall.render();
            self.backoff = 0;
            self.schedule(j.hasMore ? 0 : period());
          });
        })
        .catch(function (e) {
          // A swallowed exception here would silently freeze the wall while the console stays
          // clean -- the exact failure 实现方案 §0.5 exists to prevent. Log it, then back off.
          if (w.console && console.warn) console.warn('[poll]', e && e.message ? e.message : e);
          self.backoff = Math.min(self.backoff + 1, 4);
          self.schedule([0, 3000, 6000, 12000, 24000][self.backoff]);
        });
    },
    startPolling: function () {
      // Nothing to poll in a snapshot: the blessing set is frozen at export time, and every request
      // to /api/* would 404 on GitHub Pages (which would then log a console warning per tick).
      if (XF.cfg.snapshot) return;
      if (this.polling) return;
      this.polling = true;
      var self = this;
      d.addEventListener('visibilitychange', this._vis = function () {
        if (d.hidden) { clearTimeout(self.timer); self.timer = null; }
        else if (!self.timer) { self.schedule(0); }     // come back -> refresh at once
      });
      this.schedule(XF.cfg.pollMs);
    },
  };

  /* ══ star stream ══ */
  XF.wall = {
    TRACKS: 4, SPEED: 35, GAP: 48,
    items: [[], [], [], []],      // per track: ordered items {kind, id, el}
    els: [], offsets: [0, 0, 0, 0], load: [0, 0, 0, 0],
    paused: false, last: 0, running: false, raf: 0,

    init: function () {
      this.els = XF.util.$$('#wall-tracks .track');
      this.TRACKS = this.els.length || 4;
      var self = this;
      w.addEventListener('resize', XF.util.rafThrottle(function () { self.fill(); }));
      return this;
    },

    shortest: function () {
      var k = 0;
      for (var i = 1; i < this.TRACKS; i++) if (this.load[i] < this.load[k]) k = i;
      return k;
    },

    // A pill is capped at 76vw at roughly 15px per glyph. The old heuristic topped out near 190px
    // against a real maximum of ~296px, which skewed both the spacer borrowing and the balancing.
    estimate: function (wish) {
      var glyphs = XF.util.codepoints(wish.text) + (wish.name ? XF.util.codepoints(wish.name) : 0) + 2;
      return Math.min(Math.round(w.innerWidth * 0.78), glyphs * 15 + 40);
    },

    build: function () {
      this.resetDom();
      for (var i = 0; i < XF.data.wishes.length; i++) {
        var k = this.pushWish(XF.data.wishes[i]);
        var list = this.items[k];
        list[list.length - 1].before = null;      // first paint: plain append, nothing on screen to protect
      }
      this.fill();
      return this;
    },

    resetDom: function () {
      this.items = []; this.offsets = []; this.load = [];
      for (var i = 0; i < this.TRACKS; i++) {
        // stagger the start offset: identical offsets would stack every card into one column
        var off = i * 90 + Math.round(Math.random() * 40);
        this.items.push([]); this.offsets.push(off); this.load.push(0);
        if (!this.els[i]) continue;
        this.els[i].textContent = '';
        this.els[i].style.transform = 'translate3d(' + (-off) + 'px,0,0)';
      }
    },

    ENTRY_INSET: 40,

    // The flow element at the entry point of track i (null = past the tail).
    entryElement: function (i, entry) {
      var kids = this.els[i] ? this.els[i].children : [];
      var acc = 0;
      for (var j = 0; j < kids.length; j++) {
        acc += kids[j].offsetWidth + this.GAP;
        if (acc > entry) return kids[j];
      }
      return null;
    },

    // Prefer the shortest track whose entry point is already an empty spacer.
    pickTrack: function () {
      var best = -1, bestLoad = Infinity, fb = 0, fbLoad = Infinity;
      for (var i = 0; i < this.TRACKS; i++) {
        var entry = this.offsets[i] + Math.max(w.innerWidth, 320) - this.ENTRY_INSET;
        var el = this.entryElement(i, entry);
        if ((!el || el.className.indexOf('gap') >= 0) && this.load[i] < bestLoad) { best = i; bestLoad = this.load[i]; }
        if (this.load[i] < fbLoad) { fb = i; fbLoad = this.load[i]; }
      }
      return best >= 0 ? best : fb;
    },

    // Queue a wish so it becomes visible at once, entering from the right, with NOTHING moving and
    // nothing overlapping.
    //
    // Both extremes fail. Appending to the tail puts the card ~2 screens off-screen (it fails
    // "visible within 3 s"). Inserting into the flow at the right edge pushes everything after it
    // right -- measured 343 px of visible jump when the entry point lands on a card rather than a
    // spacer. Floating the card above the flow fixes the jump but makes arriving cards overlap each
    // other permanently: they all take the same entry point and move at the same speed.
    //
    // So: insert the card into the flow at the nearest spacer that can pay for it, and shrink that
    // spacer by exactly the card's width. The card occupies space that was already empty, every
    // element before it is untouched, and everything after it stays where it was -- the layout is
    // neutral. pickTrack routes each arrival to a different track, so a batch spreads out instead
    // of stacking.
    pushWish: function (wish) {
      var k = this.pickTrack();
      var item = { kind: 'wish', id: wish.id, wish: wish, el: null, before: null };
      var track = this.els[k];
      var est = this.estimate(wish) + this.GAP;
      var boundary = this.offsets[k] + Math.max(w.innerWidth, 320) - this.ENTRY_INSET;
      var kids = track ? track.children : [];
      var acc = 0, gapEl = null, ref = null, i, kid, kw;
      for (i = 0; i < kids.length; i++) {
        kid = kids[i]; kw = kid.offsetWidth;
        if (acc + kw >= boundary) {
          if (kid.className.indexOf('gap') >= 0 && kw >= est + 20) { gapEl = kid; break; }
          if (!ref) ref = kid;
        }
        acc += kw + this.GAP;
      }
      if (gapEl) {
        var w2 = Math.max(24, gapEl.offsetWidth - est);
        gapEl.style.width = w2 + 'px';
        if (gapEl._item) gapEl._item.width = w2;      // keep the spacer's own bookkeeping honest
        item.before = gapEl;
        this.load[k] += this.GAP;                     // the spacer paid for the card itself
      } else {
        item.before = ref;                            // rare: no spacer to borrow from
        this.load[k] += est;
      }
      this.items[k].push(item);
      return k;
    },

    // Keep every track long enough that BOTH ends stay off screen at all times (计划书 §6.4).
    //
    // The length matters in two places. A card is recycled once the track has advanced by up to
    // (widest card + GAP) = 0.76*vw + 48, and the tail must still be past the right edge at that
    // moment:  need - (0.76*vw + 48) > vw  ->  need > 1.76*vw + 48 + margin. The original 1.9*vw
    // left only ~a card's worth of slack, so a recycled card reappeared ON SCREEN at the right edge
    // -- measured as a 339 px jump on a card that had just left the left edge. 2.6*vw (>=900) fixes
    // it with margin, and arriving cards only lengthen the track further.
    fill: function () {
      var need = Math.max(w.innerWidth * 2.6, 900);
      for (var i = 0; i < this.TRACKS; i++) {
        var guard = 0;
        while (this.load[i] < need && guard++ < 30) {
          var gw = 90 + Math.round(Math.random() * 220);
          this.items[i].push({ kind: 'gap', id: 0, width: gw, el: null });
          this.load[i] += gw + this.GAP;
        }
      }
      this.render();
    },

    cardEl: function (item) {
      var wish = item.wish;
      var el = d.createElement('div');
      el.className = 'card' + (XF.data.isMine(wish.id) ? ' mine' : '');
      el.setAttribute('data-id', String(wish.id));
      var who = d.createElement('span');
      who.className = 'who';
      who.textContent = (wish.name || XF.copy.anonymous) + '：';
      var txt = d.createElement('span');
      txt.textContent = wish.text;            // textContent only -- never innerHTML (§5.5 layer 1)
      el.appendChild(who);
      el.appendChild(txt);
      if (XF.data.isMine(wish.id)) {
        var me = d.createElement('span');
        me.className = 'me';
        me.textContent = XF.copy.mine;
        el.appendChild(me);
      }
      el.addEventListener('click', function () {
        XF.wall.pause();
        XF.ui.openPause(wish);
      });
      return el;
    },

    render: function () {
      for (var i = 0; i < this.TRACKS; i++) {
        var list = this.items[i], track = this.els[i];
        for (var j = 0; j < list.length; j++) {
          var it = list[j];
          if (it.el) continue;
          if (it.kind === 'wish') {
            it.el = this.cardEl(it);
            it.el.classList.add('fresh');
          } else {
            it.el = d.createElement('div');
            it.el.className = 'gap';                // styled in app.css, never via .style.display
            it.el.style.width = it.width + 'px';
          }
          it.el._item = it;
          // insert at the entry point when one was computed, else append. `before` may have been
          // recycled in the meantime -- then it is no longer a child and we append instead.
          if (it.before && it.before.parentNode === track) track.insertBefore(it.el, it.before);
          else track.appendChild(it.el);
        }
      }
    },

    removeCard: function (id) {
      var sel = '.card[data-id="' + id + '"]';
      for (var i = 0; i < this.TRACKS; i++) {
        var el = this.els[i].querySelector(sel);
        if (!el) continue;
        el.parentNode.removeChild(el);
        for (var j = 0; j < this.items[i].length; j++) {
          if (this.items[i][j].id === id) { this.load[i] -= this.estimate(this.items[i][j].wish) + this.GAP; this.items[i].splice(j, 1); break; }
        }
        break;
      }
    },

    start: function () {
      if (this.running) return;
      this.running = true;
      var self = this;
      var step = function (t) { self.loop(t); };
      this.raf = w.requestAnimationFrame(step);
    },

    loop: function (t) {
      // Animate only while the wall is on screen. Four offsetWidth reads plus a transform write per
      // frame is real work on a low-end Android, and during the show it is invisible work (R10).
      // last is updated every frame so the stream resumes smoothly instead of teleporting.
      var visible = !!(XF.app && (XF.app.state === 'wall' || XF.app.state === 'wallModal'));
      var dt = (this.last && visible) ? (t - this.last) / 1000 : 0;
      this.last = t;
      if (dt > 0.5) dt = 0.05;              // tab was hidden: do not teleport the stream
      if (!this.paused && visible) {
        for (var i = 0; i < this.TRACKS; i++) {
          if (!this.els[i]) continue;
          this.offsets[i] += this.SPEED * dt;
          var track = this.els[i];
          var head = track.firstElementChild;
          var guard = 0;
          while (head && head.offsetWidth + this.GAP <= this.offsets[i] && guard++ < 40) {
            this.offsets[i] -= head.offsetWidth + this.GAP;
            track.appendChild(head);        // recycle to the tail: total length is unchanged
            head = track.firstElementChild;
          }
          track.style.transform = 'translate3d(' + (-this.offsets[i]).toFixed(2) + 'px,0,0)';
        }
      }
      var self = this;
      this.raf = w.requestAnimationFrame(function (tt) { self.loop(tt); });
    },

    pause: function () {
      this.paused = true;
      var el = XF.util.$('wall-tracks');
      if (el) el.classList.add('paused');   // stops ambient card animations too
    },
    resume: function () {
      this.paused = false;
      this.last = 0;
      var el = XF.util.$('wall-tracks');
      if (el) el.classList.remove('paused');
      XF.ui.closePause();
    }
  };
})(window, document);
