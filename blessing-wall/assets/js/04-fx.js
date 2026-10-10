/* 04-fx.js -- XF.fx: the six-scene choreography. One-shot performances run on WAAPI (awaitable and
   cancellable, which the hard timeouts in 09-app need); perpetual loops live in scenes.css.
   Everything animates transform/opacity only (E30). All timings are starting values from
   §7.2/§7.3/§7.4 and are meant to be tweaked. */
(function (w, d) {
  'use strict';
  var XF = w.XF;
  var anims = [], timers = [], wishPlayed = false;

  function $(id) { return d.getElementById(id); }
  function anim(el, frames, opts) { if (!el) return null; var a = el.animate(frames, opts); anims.push(a); return a; }
  function at(ms, fn) { var t = setTimeout(fn, ms); timers.push(t); return t; }
  function clearAll() {
    for (var i = 0; i < anims.length; i++) { try { anims[i].cancel(); } catch (e) { /* ignore */ } }
    for (var j = 0; j < timers.length; j++) clearTimeout(timers[j]);
    anims = []; timers = [];
  }
  function hatTransform(rot, scale) {
    return 'translateX(-50%) rotate(' + rot + 'deg) scale(' + scale + ')';
  }

  XF.fx = {
    /* hat geometry comes from sprites.js -- never hard-coded in CSS or here (实现方案 §4.3) */
    applyHatGeometry: function () {
      var S = w.XF_SPRITES || {};
      var pairs = [['fig-boy', 'boy'], ['fig-girl', 'girl']];
      var measure = function () {
        pairs.forEach(function (pair) {
          var fig = $(pair[0]); var g = S[pair[1]];
          if (!fig || !g || !g.hatAnchor) return;
          var aspect = g.hatAnchor.aspect || 1.35;
          var wPct = parseFloat(g.hatAnchor.w) / 100;
          // the brim sits at --hat-y and the cone rises above it: top = anchor - hat height.
          // The hat height in px = figureWidth * wPct * aspect, so it needs a measured width.
          var px = fig.getBoundingClientRect().width * wPct * aspect;
          fig.style.setProperty('--hat-h', px.toFixed(2) + 'px');
        });
        if (XF.fx.placeCake) XF.fx.placeCake();
      };
      pairs.forEach(function (pair) {
        var fig = $(pair[0]); var g = S[pair[1]];
        if (!fig || !g || !g.hatAnchor) return;
        fig.style.setProperty('--hat-x', g.hatAnchor.x);
        fig.style.setProperty('--hat-y', g.hatAnchor.y);
        fig.style.setProperty('--hat-w', g.hatAnchor.w);
        fig.style.setProperty('--hat-rot', g.hatAnchor.rot + 'deg');
        if (g.hatAnchor.aspect) fig.style.setProperty('--hat-a', String(g.hatAnchor.aspect));
      });
      measure();
      this._measure = measure;
      w.addEventListener('resize', measure);
      w.addEventListener('orientationchange', function () { setTimeout(measure, 250); });
    },

    // 蛋糕站在两人之间：基准取**两人各自中心的中点**，而不是"两人内缘的中点"。
    // 女孩比男孩宽 69px，内缘中点比身体中心的中点右偏约 18px —— 等宽压住两边（各 39px）看着仍偏右，
    // 用户反馈的"有一点偏右"正是这个差。左右负外边距之差 = 2×偏移量，且两者之和不变（行宽不变，
    // 整行位置不动），所以一次修正即准。
    placeCake: function () {
      var figs = XF.util.$$('#scene-wish .figure');
      var cake = d.querySelector('#scene-wish .cake-svg');
      if (!cake || figs.length < 2) return;
      var a = figs[0].getBoundingClientRect(), b = figs[1].getBoundingClientRect();
      var c = cake.getBoundingClientRect();
      var want = ((a.left + a.width / 2) + (b.left + b.width / 2)) / 2;
      var dx = want - (c.left + c.width / 2);
      if (Math.abs(dx) < 0.5) return;
      var cs = w.getComputedStyle(cake);
      var ml = parseFloat(cs.marginLeft) || 0;
      var mr = parseFloat(cs.marginRight) || 0;
      cake.style.marginLeft = (ml + dx).toFixed(2) + 'px';
      cake.style.marginRight = (mr - dx).toFixed(2) + 'px';
    },

    preloadSprites: function () {
      ['boy@4x.png', 'girl@4x.png', 'logo-96.png'].forEach(function (n) {
        var im = new Image();
        im.src = 'assets/img/' + n + (XF.cfg.build ? '?v=' + XF.cfg.build : '');
        if (im.decode) im.decode().catch(function () { /* fine */ });
      });
    },

    /* ── intro: the "20th" is thrown in, then the whole group is dragged up and off ── */
    playIntro: function (onGround, onDone) {
      clearAll();
      var twenty = d.querySelector('#scene-intro .twenty');
      var n2 = d.querySelector('#scene-intro .n2');
      var n0 = d.querySelector('#scene-intro .n0');
      var nth = d.querySelector('#scene-intro .nth');
      var crown = d.querySelector('#scene-intro .crown');
      var rays = XF.util.$$('#scene-intro .ray');
      var sub = d.querySelector('#scene-intro .intro-sub');
      var ease = 'cubic-bezier(.2,1.6,.4,1)';

      if (XF.cfg.lite) {                                  // E28: 400 ms fade, nothing else
        anim(twenty, [{ opacity: 0 }, { opacity: 1 }], { duration: 400, fill: 'forwards' });
        if (sub) sub.classList.add('on');
        at(420, onGround);
        at(760, onDone);
        return;
      }

      anim(n2, [{ transform: 'scale(2.4) translateY(-24px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 420, easing: ease, fill: 'forwards' });
      at(220, function () { anim(n0, [{ transform: 'scale(2.4) translateY(-24px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 420, easing: ease, fill: 'forwards' }); });
      at(440, function () { anim(nth, [{ transform: 'scale(1.8)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 380, easing: ease, fill: 'forwards' }); });
      at(620, function () {
        anim(crown, [{ transform: 'translateY(-60px) rotate(-14deg) scale(.8)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 520, easing: ease, fill: 'forwards' });
      });
      at(760, function () { XF.confetti.burst({ x: .5, y: .35, count: 40, spread: 78 }); });
      at(900, function () { /* the 8 balloons rise on pure CSS keyframes -- see scenes.css .balloon */ });
      at(1600, function () {
        for (var i = 0; i < rays.length; i++) {
          (function (el, i) {
            anim(el, [{ opacity: 0, transform: 'scale(.6)' }, { opacity: 1, transform: 'none' }], { duration: 600, delay: i * 80, easing: 'ease-out', fill: 'forwards' });
          })(rays[i], i);
        }
      });
      at(2600, function () { if (sub) sub.classList.add('on'); });
      at(3400, function () { if (twenty) twenty.classList.add('breathing'); });
      at(4000, function () { XF.confetti.burst({ x: .5, y: .3, count: 40, spread: 92 }); });
      at(4100, function () {                              // 收尾：整组快速上拖离屏 + 地面浮现（并行）
        if (twenty) {
          anim(twenty, [{ transform: 'translateY(0)' }, { transform: 'translateY(-120vh)' }],
            { duration: 450, easing: 'cubic-bezier(.5,0,1,1)', fill: 'forwards' });
        }
        XF.fx.sparkleTrail();
        if (onGround) onGround();
      });
      at(4560, function () { if (onDone) onDone(); });
    },

    // a short trail of sparks following the group off the top of the screen
    sparkleTrail: function () {
      var layer = $('fx-layer');
      if (!layer || XF.cfg.lite) return;
      for (var i = 0; i < 6; i++) {
        (function (i) {
          setTimeout(function () {
            var s = d.createElement('div');
            s.className = 'spark';
            s.style.left = (32 + Math.random() * 36) + 'vw';
            s.style.top = (24 + Math.random() * 26) + 'vh';
            var sz = (3 + Math.random() * 3).toFixed(1);
            s.style.width = sz + 'px'; s.style.height = sz + 'px';
            layer.appendChild(s);
            var a = s.animate([{ opacity: 0, transform: 'scale(.5)' }, { opacity: 1, transform: 'scale(1.2)' }, { opacity: 0, transform: 'translateY(-40px) scale(.4)' }],
              { duration: 620, easing: 'ease-out' });
            a.onfinish = function () { if (s.parentNode) s.parentNode.removeChild(s); };
          }, i * 60);
        })(i);
      }
    },

    /* ── transition: the ground rises from below, a warm glow sweeps over it ── */
    playGround: function () {
      var scene = $('scene-wish');
      var glow = d.querySelector('#scene-wish .warm-light');
      if (XF.cfg.lite) {
        anim(scene, [{ opacity: 0 }, { opacity: 1 }], { duration: 400, fill: 'forwards' });
        return;
      }
      anim(scene, [{ transform: 'translateY(30vh)' }, { transform: 'translateY(0)' }], { duration: 2000, easing: 'ease-out', fill: 'forwards' });
      anim(glow, [{ opacity: 0 }, { opacity: .5, offset: .45 }, { opacity: 0 }], { duration: 2000, easing: 'ease-out' });
    },

    /* ── wishScene: cake in, hats on (staggered), eyes close, wish ── */
    playWish: function () {
      if (wishPlayed) return;
      wishPlayed = true;
      var cake = d.querySelector('#scene-wish .cake-svg');
      var figs = d.querySelector('#scene-wish .wish-stage');
      var hats = [$('fig-girl').querySelector('.hat'), $('fig-boy').querySelector('.hat')];
      var S = w.XF_SPRITES || {};
      var rots = [S.girl ? S.girl.hatAnchor.rot : 0, S.boy ? S.boy.hatAnchor.rot : 0];

      if (XF.cfg.lite) {
        anim(cake, [{ opacity: 0 }, { opacity: 1 }], { duration: 400, fill: 'forwards' });
        XF.fx.wishSettle();
        return;
      }
      anim(cake, [{ transform: 'translateY(40vh)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 900, easing: 'ease-out', fill: 'forwards' });
      // 女左男右；double-checked against §7.1
      for (var i = 0; i < hats.length; i++) {
        (function (i) {
          var h = hats[i];
          if (!h) return;
          h.style.visibility = 'visible';
          at(900 + i * 220, function () {
            anim(h, [
              { transform: hatTransform(rots[i], 0) },
              { transform: hatTransform(rots[i], 1.12), offset: .55 },
              { transform: hatTransform(rots[i], .96), offset: .78 },
              { transform: hatTransform(rots[i], 1) }
            ], { duration: 460, easing: 'ease-out', fill: 'forwards' });
            if (XF.audio) XF.audio.sfx("pop");
          });
        })(i);
      }
      at(1400, function () { XF.fx.hatSparkles(); });
      at(4700, function () { if (figs) figs.classList.add('wishing'); });
    },

    hatSparkles: function () {
      var box = $('hat-sparkles');
      if (!box || XF.cfg.lite) return;
      for (var i = 0; i < 8; i++) {
        (function (i) {
          var s = d.createElement('i');
          var ang = (i / 8) * Math.PI * 2;
          s.style.left = (50 + Math.cos(ang) * 22) + '%';
          s.style.top = (34 + Math.sin(ang) * 12) + '%';
          box.appendChild(s);
          var a = s.animate([{ opacity: 0, transform: 'scale(.4)' }, { opacity: 1, offset: .3 }, { opacity: 0, transform: 'scale(1.25)' }],
            { duration: 700, delay: i * 45, easing: 'ease-out' });
          a.onfinish = function () { if (s.parentNode) s.parentNode.removeChild(s); };
        })(i);
      }
    },

    // skip: put the stage straight into its settled "wishing" pose, no performance.
    // clearAll() FIRST: playHandoff leaves fill:'forwards' animations owning transform/opacity, and
    // a running animation beats an inline style in the cascade -- without this the pose we set below
    // is silently ignored (review minor 3: 回到许愿场 landed on the zoomed-in handoff pose).
    wishSettle: function () {
      clearAll();
      var cake = d.querySelector('#scene-wish .cake-svg');
      var scene = $('scene-wish');
      var figs = d.querySelector('#scene-wish .wish-stage');
      if (scene) { scene.style.transform = 'none'; }
      if (cake) { cake.style.transform = 'none'; cake.style.opacity = '1'; }
      var hats = d.querySelectorAll('#scene-wish .hat');
      for (var i = 0; i < hats.length; i++) hats[i].style.visibility = 'visible';
      if (figs) figs.classList.add('wishing');
    },

    /* ── handoff: the wish rises to the sky, then the cake is handed over ── */
    playHandoff: function (onDone) {
      clearAll();
      var note = $('rise-note');
      var trail = $('rise-trail');
      var scene = $('scene-wish');
      var cake = d.querySelector('#scene-wish .cake-svg');
      var text = '';
      if (XF.data.wishes.length) {
        var mine = XF.data.mine;
        for (var i = 0; i < XF.data.wishes.length; i++) {
          if (mine.indexOf(XF.data.wishes[i].id) >= 0) { text = XF.data.wishes[i].text; break; }
        }
      }
      at(400, function () { XF.fx.riseNote(text); });

      if (XF.cfg.lite) {                                  // E28: 400 ms fade straight to the wall
        at(500, function () { anim(scene, [{ opacity: 1 }, { opacity: .25 }], { duration: 400, fill: 'forwards' }); });
        at(900, onDone);
        return;
      }
      at(1400, function () { anim(scene, [{ transform: 'translateY(0)' }, { transform: 'translateY(-6vh)' }], { duration: 500, easing: 'ease-in-out', fill: 'forwards' }); });
      at(1900, function () {                             // push in + a little walking bob
        anim(scene, [
          { transform: 'translateY(-6vh) scale(1)' },
          { transform: 'translateY(-4.6vh) scale(1.18)', offset: .5 },
          { transform: 'translateY(-6vh) scale(1.35)' }
        ], { duration: 1100, easing: 'ease-in-out', fill: 'forwards' });
      });
      at(3000, function () {
        // The stage is scaled 1.35 by the push-in above, so a child translate is multiplied by it.
        // -3vh lands the cake just under the screen centre AND clear of the wall modal that drops in
        // at t=4.2 s (measured: -9vh put its top at 177 while the modal card spans 76..203).
        anim(cake, [{ transform: 'none', opacity: 1 }, { transform: 'translateY(-3vh) scale(1.15)', opacity: 1 }],
          { duration: 800, easing: 'ease-out', fill: 'forwards' });
      });
      at(3400, function () { XF.confetti.burst({ x: .5, y: .58, count: 60, spread: 110 }); });
      at(4250, function () { if (onDone) onDone(); });
    },

    riseNote: function (text) {
      var note = $('rise-note');
      var trail = $('rise-trail');
      if (!note) return;
      note.textContent = text || '';
      note.style.maxWidth = '80vw';
      anim(note, [
        { opacity: 0, transform: 'translate(-50%,0) scale(.92)' },
        { opacity: 1, offset: .14 },
        { opacity: 1, offset: .72 },
        { opacity: 0, transform: 'translate(-50%,-55vh) scale(1.06)' }
      ], { duration: 1600, easing: 'cubic-bezier(.25,.1,.25,1)', fill: 'forwards' });
      if (trail) {
        anim(trail, [
          { opacity: 0, transform: 'translateX(-50%) translateY(0) scaleY(.15)' },
          { opacity: .8, offset: .3, transform: 'translateX(-50%) translateY(-16vh) scaleY(1)' },
          { opacity: 0, transform: 'translateX(-50%) translateY(-40vh) scaleY(.5)' }
        ], { duration: 1600, easing: 'cubic-bezier(.25,.1,.25,1)', fill: 'forwards' });
      }
      at(1600, function () { XF.fx.sparkle(w.innerWidth / 2, w.innerHeight * 0.22); });
    },

    sparkle: function (x, y) {
      var layer = $('fx-layer');
      if (!layer || XF.cfg.lite) return;
      var host = d.createElement('div');
      host.className = 'spark';
      host.style.left = x + 'px';
      host.style.top = y + 'px';
      host.style.width = '14px';
      host.style.height = '14px';
      host.style.marginLeft = '-7px';
      host.style.marginTop = '-7px';
      host.style.boxShadow = '0 0 18px 6px rgba(255,233,166,.95)';
      layer.appendChild(host);
      var a = host.animate([{ opacity: 0, transform: 'scale(.4)' }, { opacity: 1, transform: 'scale(1)', offset: .35 }, { opacity: 0, transform: 'scale(.6)' }],
        { duration: 520, easing: 'ease-out' });
      a.onfinish = function () { if (host.parentNode) host.parentNode.removeChild(host); };
    },

    /* ── wall: reset the stage for a fresh trip through the show ── */
    resetWishStage: function () {
      clearAll();
      wishPlayed = false;
      var scene = $('scene-wish');
      var cake = d.querySelector('#scene-wish .cake-svg');
      var figs = d.querySelector('#scene-wish .wish-stage');
      if (scene) scene.style.transform = 'none';
      if (cake) { cake.style.transform = 'none'; cake.style.opacity = '1'; }
      if (figs) figs.classList.remove('wishing');
      var hats = d.querySelectorAll('#scene-wish .hat');
      for (var i = 0; i < hats.length; i++) hats[i].style.visibility = 'visible';
    },

    cancelIntro: function () { clearAll(); }
  };
})(window, document);
