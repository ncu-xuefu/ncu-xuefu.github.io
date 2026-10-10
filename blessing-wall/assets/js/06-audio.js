/* 06-audio.js -- XF.audio: five synthesised sounds, no audio files, no background music (D12/E45).
   The AudioContext is created ONLY inside the first gate tap -- the one moment the autoplay policy
   allows it. Creating it anywhere else leaves a permanently suspended context, which on site looks
   like "some phones have sound and some don't". */
(function (w, d) {
  'use strict';
  var XF = w.XF;
  var ctx = null, bus = null, master = null, live = 0, enabled = true, broken = false;
  var crackleNodes = null;

  function noiseBuffer(seconds) {
    var n = Math.floor(ctx.sampleRate * seconds);
    var buf = ctx.createBuffer(1, n, ctx.sampleRate);
    var ch = buf.getChannelData(0);
    for (var i = 0; i < n; i++) ch[i] = Math.random() * 2 - 1;
    return buf;
  }

  function env(node, t0, peak, dur, attack) {
    var g = node.gain;
    g.cancelScheduledValues(t0);
    g.setValueAtTime(0.0001, t0);
    g.exponentialRampToValueAtTime(Math.max(0.0002, peak), t0 + (attack || 0.008));
    g.exponentialRampToValueAtTime(0.0001, t0 + dur);
  }

  function tone(type, f0, f1, dur, gain, delay) {
    var t0 = ctx.currentTime + (delay || 0);
    var osc = ctx.createOscillator();
    var g = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(f0, t0);
    if (f1 && f1 !== f0) osc.frequency.exponentialRampToValueAtTime(Math.max(1, f1), t0 + dur);
    env(g, t0, gain, dur);
    osc.connect(g); g.connect(bus);
    osc.start(t0); osc.stop(t0 + dur + 0.05);
    return osc;
  }

  function noiseHit(dur, cutoff, gain) {
    var t0 = ctx.currentTime;
    var src = ctx.createBufferSource();
    src.buffer = noiseBuffer(dur + 0.05);
    var f = ctx.createBiquadFilter();
    f.type = 'lowpass'; f.frequency.value = cutoff;
    var g = ctx.createGain();
    env(g, t0, gain, dur);
    src.connect(f); f.connect(g); g.connect(bus);
    src.start(t0); src.stop(t0 + dur + 0.05);
  }

  var SOUNDS = {
    puff: function () { noiseHit(0.18, 1200, 0.5); },                                  // 彩屑「噗」
    pop: function () { tone('sine', 660, 440, 0.12, 0.4); },                           // 弹窗「啪嗒」
    ding: function () {                                                                // 升空「叮」
      tone('sine', 880, 880, 0.35, 0.45);
      tone('sine', 1320, 1320, 0.35, 0.3, 0.06);
      tone('sine', 1760, 1760, 0.3, 0.16, 0.02);   // music-box overtone (x2)
      tone('sine', 2640, 2640, 0.25, 0.08, 0.04);  // x3
    },
    shimmer: function () { tone('sine', 1568, 1568, 0.09, 0.12); },                    // 星流入场
    sparkle: function () { tone('triangle', 1046, 1568, 0.22, 0.25); }
  };

  XF.audio = {
    unlock: function () {
      if (broken) return false;
      if (!ctx) {
        try {
          var AC = w.AudioContext || w.webkitAudioContext;
          if (!AC) { broken = true; return false; }
          ctx = new AC();
          bus = ctx.createDynamicsCompressor();
          var lp = ctx.createBiquadFilter();
          lp.type = 'lowpass'; lp.frequency.value = 6000;
          master = ctx.createGain();
          master.gain.value = enabled ? 0.22 : 0;
          bus.connect(lp); lp.connect(master); master.connect(ctx.destination);
        } catch (e) { broken = true; return false; }
      }
      if (ctx.state === 'suspended' && ctx.resume) ctx.resume().catch(function () { /* iOS may refuse */ });
      return true;
    },

    sfx: function (name) {
      if (broken || !ctx || !master) return;
      if (!enabled) return;
      if (ctx.state !== 'running') return;
      if (live >= 3) return;                       // 重叠限三并发：超出丢新
      var fn = SOUNDS[name];
      if (!fn) return;
      live++;
      try { fn(); } catch (e) { /* ignore */ }
      setTimeout(function () { live = Math.max(0, live - 1); }, 420);
    },

    // 烛火摇曳: a very quiet amplitude-modulated noise loop while the wish scene is up, and
    // ONLY if the context is already running (never a reason to create one).
    crackle: function (on) {
      if (broken || !ctx || !master) return;
      if (on && !crackleNodes && ctx.state === 'running') {
        try {
          var src = ctx.createBufferSource();
          src.buffer = noiseBuffer(2);
          src.loop = true;
          var f = ctx.createBiquadFilter();
          f.type = 'lowpass'; f.frequency.value = 420;
          var g = ctx.createGain();
          g.gain.value = 0.0001;
          var lfo = ctx.createOscillator();
          var lfoGain = ctx.createGain();
          lfo.frequency.value = 3;
          lfoGain.gain.value = 0.03;
          lfo.connect(lfoGain); lfoGain.connect(g.gain);
          src.connect(f); f.connect(g); g.connect(bus);
          src.start(); lfo.start();
          g.gain.exponentialRampToValueAtTime(0.06, ctx.currentTime + 1.2);
          crackleNodes = { src: src, lfo: lfo, g: g };
        } catch (e) { /* ignore */ }
      } else if (!on && crackleNodes) {
        try {
          crackleNodes.g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.4);
          crackleNodes.src.stop(ctx.currentTime + 0.5);
          crackleNodes.lfo.stop(ctx.currentTime + 0.5);
        } catch (e) { /* ignore */ }
        crackleNodes = null;
      }
    },

    setEnabled: function (v) {
      enabled = !!v;
      XF.util.store.set('xf20.sound', enabled);
      if (master) { try { master.gain.value = enabled ? 0.22 : 0; } catch (e) { /* ignore */ } }
      var b = XF.util.$('btn-sound');
      if (b) b.classList.toggle('muted', !enabled);
      if (enabled && ctx && ctx.state === 'suspended' && ctx.resume) ctx.resume().catch(function () { /* ignore */ });
    },
    isEnabled: function () { return enabled; },

    init: function () {
      enabled = XF.util.store.get('xf20.sound', true) !== false;
      var b = XF.util.$('btn-sound');
      b.classList.toggle('muted', !enabled);
      b.addEventListener('click', function () { XF.audio.setEnabled(!XF.audio.isEnabled()); });
    }
  };
})(window, document);
