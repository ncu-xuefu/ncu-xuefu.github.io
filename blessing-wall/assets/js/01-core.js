/* 01-core.js -- XF.util / XF.copy / XF.cfg. Loaded first; everything else hangs off window.XF. */
(function (w, d) {
  'use strict';
  var XF = (w.XF = w.XF || {});

  // ---- copy: the single source of every user-visible string (附录 A) ----
  XF.copy = {
    title: '小服 20 岁生日快乐',
    gateHint: '轻触屏幕 为小服庆生',
    skip: '跳过',
    introSub: '生日快乐 · 2006→2026',
    yearEgg: '2006 → 2026',
    composeTitle: '在下面写下你对小服的祝福吧',
    composePlaceholder: '写点什么吧，小服在听…',
    nameLabel: '署名（选填）：',
    submit: '送给小服',
    count: function (n, max) { return n + '/' + max; },
    wallModalTitle: '看看别人对小服的祝福吧',
    wallModalGo: '看看',
    wallTitle: '小服的 20 岁祝福墙',
    writeMore: '再写一条祝福',
    backWish: '回到许愿场',
    close: '关闭',
    mine: '我',
    anonymous: '匿名',
    shareTitle: '我的祝福卡',
    shareHint: '长按图片保存到相册',
    // WeChat cannot save a blob:/data: image -- only an http(s) one. So while the card is still
    // being uploaded the hint must NOT invite a long-press: the user long-presses, WeChat says
    // 「保存图片失败」, and it looks like the app is broken (field report from the first real test).
    sharePreparing: '图片正在上传，稍等一下…',
    shareFailed: '图片没传完，稍后再长按试试',
    soundLabel: '声音开关',
    adminTitle: '管理',
    adminDelete: '删除',
    adminUndo: '撤销',
    adminFreeze: '冻结提交',
    adminThaw: '恢复提交',
    adminUndone: '已删除，10 秒内可撤销',
    adminWrongKey: '口令好像不对哦',
    errRateLimited: '慢一点，小服还在听～',
    errTooLong: '祝福太长啦，小服记不住～',
    errLinkBlocked: '小服看不懂链接哦',
    errSensitive: '这句话小服收不下',
    errFrozen: '小服先去准备生日啦，稍等一下～',
    errGeneric: '哎呀，出了点小差错，再试一次吧',
    offline: '小服正在努力接上…'
  };

  // ---- config (filled from /api/config, then URL flags) ----
  XF.cfg = { pollMs: 2000, limits: { nameMax: 12, textMax: 120, pollMs: 2000, wallPage: 50 }, build: '', hasBgm: false, lite: false, bare: false, snapshot: false };

  var LS_OK = (function () { try { w.localStorage.setItem('xf20.t', '1'); w.localStorage.removeItem('xf20.t'); return true; } catch (e) { return false; } })();
  var mem = {};

  XF.util = {
    $: function (id) { return d.getElementById(id); },
    $$: function (sel, root) { return Array.prototype.slice.call((root || d).querySelectorAll(sel)); },

    store: {                       // localStorage with an in-memory fallback (private mode throws)
      get: function (k, dflt) {
        try {
          var raw = LS_OK ? w.localStorage.getItem(k) : mem[k];
          return raw == null ? dflt : JSON.parse(raw);
        } catch (e) { return dflt; }
      },
      set: function (k, v) {
        var raw = JSON.stringify(v);
        try { if (LS_OK) w.localStorage.setItem(k, raw); else mem[k] = raw; } catch (e) { mem[k] = raw; }
      }
    },

    // E41: crypto.randomUUID is undefined on plain http (the LAN fallback is not a secure
    // context), which would break submission on the one channel that must always work.
    uuidv4: function () {
      var b = new Uint8Array(16);
      (w.crypto && w.crypto.getRandomValues) ? w.crypto.getRandomValues(b) : (function () { for (var i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256); })();
      b[6] = (b[6] & 0x0f) | 0x40;
      b[8] = (b[8] & 0x3f) | 0x80;
      var h = [];
      for (var i = 0; i < 16; i++) h.push((b[i] + 0x100).toString(16).slice(1));
      return h.slice(0, 4).join('') + '-' + h.slice(4, 6).join('') + '-' + h.slice(6, 8).join('') + '-' + h.slice(8, 10).join('') + '-' + h.slice(10, 16).join('');
    },
    clientId: function () {
      var c = XF.util.store.get('xf20.cid', '');
      if (!c) { c = XF.util.uuidv4(); XF.util.store.set('xf20.cid', c); }
      return c;
    },

    clamp: function (v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); },

    // TRUE codepoints (E32). The obvious `.length` counts UTF-16 units, which doubles every emoji:
    // a blessing with 60 emoji would read 120/120 on screen while the server (which counts
    // codepoints) would still accept more. Surrogate pairs are counted once.
    codepoints: function (s) {
      var str = String(s == null ? '' : s);
      var pairs = str.match(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g);
      return str.length - (pairs ? pairs.length : 0);
    },
    // Slice by codepoint, never mid-surrogate (half a pair renders as a broken glyph).
    cpSlice: function (s, n) {
      var str = String(s == null ? '' : s), out = '', count = 0, i = 0;
      while (i < str.length && count < n) {
        var hi = str.charCodeAt(i);
        var len = (hi >= 0xD800 && hi <= 0xDBFF && i + 1 < str.length &&
                   str.charCodeAt(i + 1) >= 0xDC00 && str.charCodeAt(i + 1) <= 0xDFFF) ? 2 : 1;
        out += str.substr(i, len);
        count++; i += len;
      }
      return out;
    },
    // Strip what the server rejects but the visitor cannot see (control + zero-width, keeping ZWJ so
    // family emoji survive). Without this, one invisible character pasted from WeChat produces
    // 「哎呀，出了点小差错」 -- an error that names nothing and is unfixable by retrying.
    sanitize: function (s) {
      return String(s == null ? '' : s)
        .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
        .replace(/[\u200B\u200C\u200E\u200F\u202A-\u202E\u2060-\u2064\uFEFF]/g, '')
        .replace(/\r\n?/g, '\n')
        .replace(/\t/g, ' ');
    },
    now: function () { return Date.now() + XF.util.skew; },
    skew: 0,

    // relative time is always computed against the SERVER clock (phone clocks drift wildly)
    fmtRelTime: function (ts) {
      var s = Math.max(0, (XF.util.now() - ts) / 1000);
      if (s < 60) return '刚刚';
      if (s < 3600) return Math.floor(s / 60) + ' 分钟前';
      if (s < 86400) return Math.floor(s / 3600) + ' 小时前';
      if (s < 604800) return Math.floor(s / 86400) + ' 天前';
      var dt = new Date(ts);
      return (dt.getMonth() + 1) + '月' + dt.getDate() + '日';
    },

    fetchConfig: function () {
      // A snapshot (tools/snapshot.mjs) reads its config off its own directory, so the copy needs no
      // server: the same shape the API returns, minus `now` (a baked `now` would skew every relative
      // time on the wall by however long the page has been published).
      return fetch(XF.cfg.snapshot ? 'assets/data/config.json' : '/api/config', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j && j.limits) XF.cfg.limits = j.limits;
          if (j) { XF.cfg.build = j.build; XF.cfg.hasBgm = !!j.hasBgm; }
          if (j && j.now) XF.util.skew = j.now - Date.now();
          return j;
        })
        .catch(function () { return null; });
    },

    rafThrottle: function (fn) {
      var queued = false, lastArgs;
      return function () {
        lastArgs = arguments;
        if (queued) return;
        queued = true;
        w.requestAnimationFrame(function () { queued = false; fn.apply(null, lastArgs); });
      };
    }
  };
})(window, document);
