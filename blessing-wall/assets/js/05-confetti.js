/* 05-confetti.js -- XF.confetti: a thin, defensive wrapper around the vendored canvas-confetti.
   E40's four traps:
     1. the bundle is CommonJS -> typeof check, never assume it loaded;
     2. resize:true ignores devicePixelRatio (blurry on retina) -> we own the canvas size;
     3. the resize must fire when the viewport GROWS (keyboard down, rotation) but not when it
        shrinks, or typing would clear the canvas mid-burst;
     4. a canvas without pointer-events:none swallows every tap -- the gate would look dead. */
(function (w, d) {
  'use strict';
  var XF = w.XF;
  var COLORS = ['#FEDF8D', '#FE926D', '#2E5EA3', '#FFF6DD', '#E8A93C', '#DEEAF6'];
  var fire = null, canvas = null, density = 80, lastW = 0, lastH = 0, resizeQueued = false;

  function sizeUp(force) {
    if (!canvas) return;
    var dpr = Math.min(w.devicePixelRatio || 1, 2);
    var wpx = Math.round((w.visualViewport ? w.visualViewport.width : w.innerWidth) * dpr);
    var hpx = Math.round((w.visualViewport ? w.visualViewport.height : w.innerHeight) * dpr);
    if (!force && (wpx <= lastW && hpx <= lastH)) return;   // shrink: leave the burst alone
    if (wpx === lastW && hpx === lastH) return;
    lastW = wpx; lastH = hpx;
    canvas.width = wpx;
    canvas.height = hpx;
  }

  XF.confetti = {
    init: function () {
      canvas = XF.util.$('fx');
      if (!canvas) return false;
      if (typeof w.confetti !== 'function') {
        // Silently degrade: everything else must still work (module-level ReferenceError in the
        // vendor bundle looks exactly like "no confetti, console clean").
        if (w.console && console.warn) console.warn('[fx] confetti unavailable');
        return false;
      }
      try {
        fire = w.confetti.create(canvas, { resize: false, useWorker: false });
        sizeUp(true);
        var vv = w.visualViewport;
        var onResize = function () {
          if (resizeQueued) return;
          resizeQueued = true;
          w.requestAnimationFrame(function () { resizeQueued = false; sizeUp(false); });
        };
        if (vv) { vv.addEventListener('resize', onResize); vv.addEventListener('scroll', onResize); }
        w.addEventListener('orientationchange', function () { setTimeout(function () { sizeUp(true); }, 250); });
        return true;
      } catch (e) {
        fire = null;
        return false;
      }
    },

    setDensity: function (n) { density = n; },

    burst: function (o) {
      if (!fire) return;
      o = o || {};
      var n = Math.min(o.count || 40, density);
      if (n <= 0) return;
      if (XF.audio && XF.audio.sfx) XF.audio.sfx('puff');   // §11.2: the burst's 噗 (was never wired)
      try {
        fire({
          particleCount: n,
          spread: o.spread == null ? 70 : o.spread,
          startVelocity: o.velocity || 42,
          ticks: 180,
          gravity: o.gravity || 0.9,
          scalar: o.scalar || 1,
          origin: { x: o.x == null ? 0.5 : o.x, y: o.y == null ? 0.35 : o.y },
          colors: COLORS,
          disableForReducedMotion: true
        });
      } catch (e) { /* never let a decorative burst break the flow */ }
    }
  };
})(window, document);
