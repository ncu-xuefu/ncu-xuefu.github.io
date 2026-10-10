/* 08-admin.js -- XF.admin: hidden entry (7 taps on the wall emblem inside 5 s) + Bearer token,
   soft delete with a 10 s undo, freeze/thaw (E15/E16).
   The entry hangs off the WALL emblem only: the gate emblem is the "tap anywhere to start"
   target, so counting taps there would fight the state machine. */
(function (w, d) {
  'use strict';
  var XF = w.XF;
  var taps = [], token = '', mode = false, undoId = 0, undoTimer = null;

  function authed(opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers.Authorization = 'Bearer ' + token;
    return fetch(opts.url, opts).then(function (r) {
      if (r.status === 401 || r.status === 404) { mode = false; token = ''; }
      return r.json().catch(function () { return {}; }).then(function (j) { return { status: r.status, j: j }; });
    });
  }

  XF.admin = {
    armEntry: function () {
      var el = XF.util.$('wall-emblem');
      if (!el || el._armed) return;
      el._armed = true;
      el.addEventListener('click', function () {
        var now = Date.now();
        taps = taps.filter(function (t) { return now - t < 5000; });
        taps.push(now);
        if (taps.length >= 7) { taps = []; XF.ui.openAdmin(); }
      });
    },

    login: function () {
      token = (XF.util.$('admin-token').value || '').trim();
      if (!token) return;
      authed({ url: '/api/admin/all', headers: { 'Content-Type': 'application/json' } }).then(function (res) {
        if (res.status === 200 && res.j && res.j.ok) {
          mode = true;
          XF.util.$('admin-token').value = '';
          XF.ui.closeAdmin();
          XF.ui.adminMsg('');
          XF.admin.syncDeleteButton();
        } else if (res.status === 401) {
          mode = false;
          XF.ui.adminMsg(XF.copy.adminWrongKey);      // distinguishable from "something broke"
        } else if (res.status === 429) {
          mode = false;
          XF.ui.adminMsg(XF.copy.errRateLimited);
        } else {
          mode = false;
          XF.ui.adminMsg(XF.copy.errGeneric);         // 404 = the admin surface is switched off
        }
      }).catch(function () { XF.ui.adminMsg(XF.copy.offline); });
    },

    setState: function (accepting) {
      if (!mode) return;
      authed({
        url: '/api/admin/state', method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ accepting: accepting })
      }).then(function (res) {
        XF.ui.adminMsg(res.status === 200 ? (accepting ? XF.copy.adminThaw : XF.copy.adminFreeze) : XF.copy.errGeneric);
      }).catch(function () { XF.ui.adminMsg(XF.copy.offline); });
    },

    // the delete affordance only exists in the pause card, and only after login
    syncDeleteButton: function () {
      var b = XF.util.$('btn-pause-delete');
      if (b) b.classList.toggle('off', !mode);
    },

    remove: function (id) {
      if (!mode) return;
      authed({ url: '/api/wishes/' + id, method: 'DELETE' }).then(function (res) {
        if (res.status !== 200) { XF.ui.toast(XF.copy.errGeneric); return; }
        undoId = id;
        if (XF.wall) XF.wall.removeCard(id);
        delete XF.data.ids[id];
        XF.ui.closePause();
        XF.admin.showUndo(true);
        clearTimeout(undoTimer);
        undoTimer = setTimeout(function () { XF.admin.showUndo(false); }, 10000);   // 10 s window
      }).catch(function () { XF.ui.toast(XF.copy.offline); });
    },

    undo: function () {
      if (!mode || !undoId) return;
      authed({
        url: '/api/admin/restore', method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: undoId })
      }).then(function (res) {
        if (res.status === 200) {
          XF.admin.showUndo(false);
          undoId = 0;
          XF.data.reloadAll();
        } else { XF.ui.toast(XF.copy.errGeneric); }
      }).catch(function () { XF.ui.toast(XF.copy.offline); });
    },

    showUndo: function (on) {
      var bar = XF.util.$('undo-bar');
      if (!bar) return;
      bar.classList.toggle('off', !on);
      var t = XF.util.$('undo-text');
      if (t) t.textContent = XF.copy.adminUndone;
      var b = XF.util.$('btn-undo');
      if (b) b.textContent = XF.copy.adminUndo;
    }
  };
})(window, document);
