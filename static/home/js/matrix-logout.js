/**
 * 金格Pi 退出登录时清理 Matrix / FluffyChat 浏览器会话（同源 localStorage + IndexedDB）。
 */
(function (global) {
  "use strict";

  var KEEP_LOCAL_KEYS = {
    theme_mode: 1,
    primary_color: 1,
    "chat.fluffy.color_scheme_seed": 1,
    "chat.fluffy.default_homeserver": 1,
    jingepi_public_base: 1,
    jingepi_fluffy_theme_ver: 1,
  };

  var KEEP_LOCAL_PREFIXES = ["jingepi_", "jingepi-"];

  function shouldKeepLocalKey(key) {
    if (!key) return true;
    if (KEEP_LOCAL_KEYS[key]) return true;
    var bare = key.indexOf("flutter.") === 0 ? key.slice(8) : key;
    if (KEEP_LOCAL_KEYS[bare]) return true;
    for (var i = 0; i < KEEP_LOCAL_PREFIXES.length; i++) {
      if (key.indexOf(KEEP_LOCAL_PREFIXES[i]) === 0) return true;
    }
    return false;
  }

  function shouldRemoveLocalKey(key) {
    if (!key || shouldKeepLocalKey(key)) return false;
    if (key === "flutter-web-auth-2") return true;
    if (/LocalStorage/i.test(key)) return true;
    if (/matrix|fluffy|synapse|cinny_access|client_name|device_id|user_id|access_token/i.test(key)) {
      return true;
    }
    if (key.indexOf("flutter.") === 0) {
      var bare = key.slice(8);
      if (/client|account|token|matrix|olm|session|login|credential|user_device|homeserver/i.test(bare)) {
        return true;
      }
    }
    return false;
  }

  function collectMatrixTokens() {
    var tokens = [];
    var seen = {};
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var key = localStorage.key(i);
        if (!key) continue;
        var val = localStorage.getItem(key);
        if (!val) continue;
        try {
          var parsed = JSON.parse(val);
          if (parsed && typeof parsed === "object") {
            if (parsed.token && !seen[parsed.token]) {
              seen[parsed.token] = 1;
              tokens.push(parsed.token);
            }
            if (parsed.access_token && !seen[parsed.access_token]) {
              seen[parsed.access_token] = 1;
              tokens.push(parsed.access_token);
            }
          }
        } catch (e) {
          /* not json */
        }
      }
    } catch (e2) {
      /* ignore */
    }
    return tokens;
  }

  function clearLocalMatrixSession() {
    try {
      var keys = [];
      for (var i = 0; i < localStorage.length; i++) {
        keys.push(localStorage.key(i));
      }
      keys.forEach(function (key) {
        if (shouldRemoveLocalKey(key)) {
          try {
            localStorage.removeItem(key);
          } catch (e) {}
        }
      });
    } catch (e) {}
  }

  // FluffyChat（Flutter web）把 Matrix 会话存在 Hive/IndexedDB 里，库名随 app 显示名
  // 变化（当前为 "金格Pi聊天室 web"）。只按英文关键词匹配会漏掉这个中文库名，导致退出
  // 登录时库没被删、下次进聊天室仍自动登录。故同时按中文品牌词匹配，并兜底直接删除已知
  // 库名（兼容不支持 indexedDB.databases() 的浏览器，如 Firefox / Safari）。
  var KNOWN_FLUFFY_DB_NAMES = ["金格Pi聊天室 web", "FluffyChat web", "fluffychat web"];

  function shouldDeleteIdb(name) {
    if (!name) return false;
    return /matrix|fluffy|fluffychat|localstorage|olm|sqflite|cinny|金格|聊天室|jingepi/i.test(
      name
    );
  }

  function deleteIndexedDb(name) {
    return new Promise(function (resolve) {
      if (!name) {
        resolve();
        return;
      }
      var done = false;
      function finish() {
        if (!done) {
          done = true;
          resolve();
        }
      }
      try {
        var req = indexedDB.deleteDatabase(name);
        req.onsuccess = finish;
        req.onerror = finish;
        // 连接仍被占用（典型：/chat 内的 FluffyChat iframe 还没卸载）时 deleteDatabase
        // 会被 blocked；请求会在连接释放后自动完成。这里不立即 resolve，给它一点时间，
        // 再用兜底超时收尾，避免一直挂起阻塞跳转。
        req.onblocked = function () {
          setTimeout(finish, 1500);
        };
        setTimeout(finish, 3000);
      } catch (e) {
        finish();
      }
    });
  }

  function clearIndexedDbMatrixSession() {
    if (!global.indexedDB) return Promise.resolve();
    var tasks = [];
    var dispatched = {};
    function dispatch(name) {
      if (!name || dispatched[name]) return;
      dispatched[name] = 1;
      tasks.push(deleteIndexedDb(name));
    }
    // 兜底：直接删除已知的 FluffyChat 库名（无 indexedDB.databases() 时也能工作）
    KNOWN_FLUFFY_DB_NAMES.forEach(dispatch);
    try {
      var databasesFn = global.indexedDB.databases;
      if (typeof databasesFn === "function") {
        var listing = databasesFn.call(global.indexedDB);
        if (listing && listing.then) {
          return listing
            .then(function (dbs) {
              (dbs || []).forEach(function (db) {
                var name = db && db.name;
                if (name && shouldDeleteIdb(name)) dispatch(name);
              });
              return Promise.all(tasks);
            })
            .catch(function () {
              return Promise.all(tasks);
            });
        }
      }
    } catch (e) {
      /* ignore */
    }
    return Promise.all(tasks);
  }

  function logoutMatrixTokens(tokens) {
    if (!tokens || !tokens.length) return Promise.resolve();
    return Promise.all(
      tokens.map(function (token) {
        return fetch("/_matrix/client/v3/logout", {
          method: "POST",
          headers: { Authorization: "Bearer " + token },
          credentials: "same-origin",
        }).catch(function () {});
      })
    );
  }

  function clearMatrixSession() {
    var tokens = collectMatrixTokens();
    return logoutMatrixTokens(tokens)
      .then(function () {
        clearLocalMatrixSession();
        return clearIndexedDbMatrixSession();
      });
  }

  function run(opts) {
    opts = opts || {};
    var redirect = opts.redirect || "/";
    return clearMatrixSession().then(function () {
      if (opts.redirect === false) return;
      try {
        global.location.replace(redirect);
      } catch (e) {
        global.location.href = redirect;
      }
    });
  }

  global.JingepiMatrixLogout = {
    clearMatrixSession: clearMatrixSession,
    run: run,
  };
})(typeof window !== "undefined" ? window : this);
