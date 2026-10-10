/* 07-share.js -- XF.share: compose the blessing card on a canvas, then post it back (E43/E44).
   Two-layer safety net: the blob URL shows immediately, and once the upload lands we swap to the
   server URL -- only a real http(s) image gets a reliable long-press "save to album" menu. */
(function (w, d) {
  'use strict';
  var XF = w.XF;
  var W = 1080, PAD = 72, CARD_PAD = 48;
  var FONT = '"PingFang SC","Microsoft YaHei",system-ui,sans-serif';

  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function loadImg(src) {
    return new Promise(function (res) {
      var im = new Image();
      im.onload = function () { res(im); };
      im.onerror = function () { res(null); };
      im.src = src;
    });
  }
  function roundRect(ctx, x, y, w2, h2, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w2, y, x + w2, y + h2, r);
    ctx.arcTo(x + w2, y + h2, x, y + h2, r);
    ctx.arcTo(x, y + h2, x, y, r);
    ctx.arcTo(x, y, x + w2, y, r);
    ctx.closePath();
  }

  function wrap(ctx, text, maxW, maxLines) {
    var lines = [], cur = '';
    var chars = Array.prototype.slice.call(text);
    for (var i = 0; i < chars.length; i++) {
      var ch = chars[i];
      if (ch === '\n') { lines.push(cur); cur = ''; if (lines.length >= maxLines) break; continue; }
      if (ctx.measureText(cur + ch).width > maxW && cur) { lines.push(cur); cur = ''; if (lines.length >= maxLines) break; }
      cur += ch;
    }
    if (lines.length < maxLines && cur) lines.push(cur);
    if (lines.length >= maxLines) {                       // 第 8 行溢出截断
      var last = lines[maxLines - 1];
      while (last.length > 1 && ctx.measureText(last + '…').width > maxW) last = last.slice(0, -1);
      var rest = Array.prototype.slice.call(text).join('');
      if (ctx.measureText(lines.join('') + '…').width > ctx.measureText(rest).width) lines[maxLines - 1] = last + '…';
    }
    return lines.slice(0, maxLines);
  }

  XF.share = {
    draw: function (wish, imgs) {
      var c = d.createElement('canvas');
      var ctx = c.getContext('2d');
      ctx.font = '600 44px ' + FONT;
      var maxTextW = W - 2 * PAD - 2 * CARD_PAD;
      var lines = wrap(ctx, wish.text || '', maxTextW, 8);
      var lineH = Math.round(44 * 1.6);
      var cardH = Math.max(240, lines.length * lineH + 2 * CARD_PAD + 40);
      var headH = 430, footH = 360;
      // The canvas has a floor of 1350 px (E43). A short blessing would otherwise leave all the
      // slack as one hole between the card and the characters; centring the whole block splits it
      // into an even top/bottom margin, which reads as a deliberate print instead.
      var natural = headH + cardH + footH;
      var H = Math.max(1350, Math.min(2100, Math.round(natural / 8) * 8));
      var y0 = Math.max(0, Math.round((H - natural) / 2));
      c.width = W; c.height = H;

      // background
      var g = ctx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, '#FFF6DD'); g.addColorStop(1, '#FDFBF4');
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

      // seeded confetti dots -- same wish always renders the same card
      var rnd = mulberry32((wish.id || 1) * 2654435761 % 4294967296);
      var pal = ['#FE926D', '#FEDF8D', '#2E5EA3'];
      for (var i = 0; i < 120; i++) {
        ctx.globalAlpha = 0.18 + rnd() * 0.22;
        ctx.fillStyle = pal[i % 3];
        var r = 3 + rnd() * 6;
        ctx.beginPath(); ctx.arc(rnd() * W, rnd() * H, r, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;

      // watermark
      ctx.save();
      ctx.globalAlpha = 0.15; ctx.fillStyle = '#FE926D';
      ctx.translate(W - 40, 330 + y0); ctx.rotate(-8 * Math.PI / 180);
      ctx.font = '700 190px ' + FONT; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText('20th', 0, 0);
      ctx.restore();

      // emblem + org + anniversary
      ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
      if (imgs.logo) ctx.drawImage(imgs.logo, W / 2 - 48, y0 + 92, 96, 96);
      ctx.fillStyle = '#794D44';
      ctx.font = '600 34px ' + FONT;
      ctx.fillText('南昌大学教务处学生学习服务中心', W / 2, y0 + 252);
      ctx.fillStyle = '#8a7f78';
      ctx.font = '26px ' + FONT;
      ctx.fillText('2006.10.10 — 2026.10.10 · 20 周年', W / 2, y0 + 300);

      // white card
      var cardY = y0 + headH - 40;
      ctx.save();
      ctx.shadowColor = 'rgba(121,77,68,.18)'; ctx.shadowBlur = 26; ctx.shadowOffsetY = 8;
      ctx.fillStyle = 'rgba(255,255,255,.96)';
      roundRect(ctx, PAD, cardY, W - 2 * PAD, cardH, 36); ctx.fill();
      ctx.restore();

      ctx.fillStyle = '#1F2329';
      ctx.font = '600 44px ' + FONT;
      ctx.textAlign = 'left';
      var ty = cardY + CARD_PAD + 46;
      for (var k = 0; k < lines.length; k++) { ctx.fillText(lines[k], PAD + CARD_PAD, ty + k * lineH); }

      // divider (flame recipe, same as the portal)
      var dy = cardY + cardH - 92;
      var fg = ctx.createLinearGradient(PAD + CARD_PAD, 0, W - PAD - CARD_PAD, 0);
      fg.addColorStop(0, '#D92419'); fg.addColorStop(0.5, '#DC8C0F'); fg.addColorStop(1, '#E3C238');
      ctx.fillStyle = fg;
      ctx.fillRect(PAD + CARD_PAD, dy, W - 2 * PAD - 2 * CARD_PAD, 4);

      // signature
      ctx.fillStyle = '#794D44';
      ctx.font = '600 38px ' + FONT;
      ctx.textAlign = 'right';
      ctx.fillText('—— ' + (wish.name || XF.copy.anonymous), W - PAD - CARD_PAD, dy + 66);

      // figures + footer
      var baseY = y0 + natural - 180;
      var girlH = 180, boyH = 225;
      var girlW = imgs.girl ? girlH * (imgs.girl.naturalWidth / imgs.girl.naturalHeight) : 0;
      var boyW = imgs.boy ? boyH * (imgs.boy.naturalWidth / imgs.boy.naturalHeight) : 0;
      var totalW = girlW + boyW + 40;
      var x0 = W / 2 - totalW / 2;
      var girlY = baseY - girlH + 130, boyY = baseY - boyH + 130;
      if (imgs.girl) ctx.drawImage(imgs.girl, x0, girlY, girlW, girlH);
      if (imgs.boy) ctx.drawImage(imgs.boy, x0 + girlW + 40, boyY, boyW, boyH);
      ctx.textAlign = 'center';
      ctx.fillStyle = '#794D44';
      ctx.font = '600 40px ' + FONT;
      ctx.fillText('小服 · 20 岁生日快乐', W / 2, H - 66);
      return c;
    },

    // Retry the network image a few times: a single failed fetch of /s/<id>.png used to leave the
    // <img> on its blob: URL forever, and a blob: image cannot be saved by WeChat at all.
    loadNet: function (src, onReady) {
      var n = 0, tries = 6;
      var attempt = function () {
        var im = new Image();
        im.onload = function () { onReady(src); };
        im.onerror = function () {
          if (++n >= tries) { onReady(null); return; }
          setTimeout(attempt, 900 * n);          // backoff
        };
        im.src = src + '&r=' + n;                // defeat the browser's cache of a failed load
      };
      attempt();
    },

    make: function (wish, onReady) {
      if (XF.cfg.bare) { if (onReady) onReady(null); return Promise.resolve({}); }
      var q = XF.cfg.build ? '?v=' + XF.cfg.build : '';
      return Promise.all([
        loadImg('assets/img/logo-512.png' + q),
        loadImg('assets/img/girl@4x.png' + q),
        loadImg('assets/img/boy@4x.png' + q)
      ]).then(function (arr) {
        var canvas = XF.share.draw(wish, { logo: arr[0], girl: arr[1], boy: arr[2] });
        return new Promise(function (res) {
          var encode = function (cb) {
            canvas.toBlob(function (b) {
              if (b) { cb(b, 'image/jpeg'); return; }
              canvas.toBlob(function (p2) { cb(p2, 'image/png'); }, 'image/png');   // very old engines
            }, 'image/jpeg', 0.92);
          };
          encode(function (blob, mime) {
            if (!blob) { res({ textOnly: true }); return; }
            var blobUrl = URL.createObjectURL(blob);
            if (blob.size > 6 * 1024 * 1024) { res({ blobUrl: blobUrl }); return; }   // E44: 超限保留 blob 图
            var up = function (n) {
              return fetch('/api/share/' + wish.id, { method: 'POST', headers: { 'Content-Type': mime }, body: blob })
                .then(function (r) { return r.json(); })
                .then(function (j) {
                  if (!j || !j.ok) throw new Error('upload ' + (j && j.code));
                  var url = (j.url || ('/s/' + wish.id + '.png')) + '?v=' + Date.now();
                  res({ blobUrl: blobUrl, netUrl: url });
                  if (onReady) XF.share.loadNet(url, onReady);
                })
                .catch(function (e) {
                  if (n < 3) { setTimeout(function () { up(n + 1); }, 1200 * (n + 1)); return; }   // retry the upload
                  res({ blobUrl: blobUrl, uploadFailed: true });
                  if (onReady) onReady(null);
                });
            };
            up(1);
          }, 'image/png');
        });
      }).catch(function () { return { textOnly: true }; });
    }
  };
})(window, document);
