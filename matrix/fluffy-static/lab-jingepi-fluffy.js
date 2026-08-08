/**
 * 金格Pi × FluffyChat Web — 启动前偏好锁定 + 壳层就绪标记
 *
 * FluffyChat 用 Material3 ColorScheme.fromSeed(colorSchemeSeedInt)。
 * Canvas 内按钮的 hover/press/focus/disabled 由 Material 状态层绘制，
 * 无法用 CSS 改成玻璃态；此处把种子色锁为金格金，并强制深色模式。
 *
 * SharedPreferences（Web）通常写入 localStorage，键带 flutter. 前缀，值为 JSON。
 * 同时写入无前缀键，兼容部分 Async API。
 */
(function () {
  /* SSO 回调：Synapse 常把 loginToken 挂在 /fluffychat/?loginToken=…
   * FluffyChat Web 靠 flutter-web-auth-2 的 postMessage / localStorage 收凭证。
   * 必须在 Flutter 启动前执行。 */
  (function handleSsoCallbackEarly() {
    var search = window.location.search || "";
    if (!/(?:^|[?&])loginToken=/.test(search)) return;
    var href = window.location.href;
    var payload = { "flutter-web-auth-2": href };
    var origin = window.location.origin;
    try {
      localStorage.setItem("flutter-web-auth-2", href);
    } catch (e) {}
    if (window.opener && window.opener !== window) {
      try {
        window.opener.postMessage(payload, origin);
      } catch (e) {}
      try {
        window.close();
      } catch (e) {}
      return;
    }
    /* 仅 auth.html 回调页通知父 frame；正常 /fluffychat/ 由 Flutter 自己读 URL */
    if (/\/auth\.html$/i.test(window.location.pathname) && window.parent && window.parent !== window) {
      try {
        window.parent.postMessage(payload, origin);
      } catch (e) {}
    }
  })();

  var GOLD = 0xfff0b90b; /* #f0b90b → 4293966091 */
  var GOLD_STR = String(GOLD >>> 0);
  var THEME_VER = "jingepi-fluffy-theme-v2";

  function setJson(key, jsonLiteral) {
    try {
      localStorage.setItem("flutter." + key, jsonLiteral);
    } catch (e) {}
    try {
      localStorage.setItem(key, jsonLiteral);
    } catch (e) {}
  }

  function syncHomeserverNow() {
    var hs = window.__JINGEPI_HOMESERVER__;
    if (typeof hs !== "string" || !hs) {
      try {
        hs = localStorage.getItem("jingepi_public_base") || "";
      } catch (e) {
        hs = "";
      }
    }
    hs = String(hs).replace(/\/+$/, "");
    if (!hs) return;
    setJson("chat.fluffy.default_homeserver", JSON.stringify(hs));
    try {
      localStorage.setItem("jingepi_public_base", hs);
    } catch (e) {}
  }

  function lockBrandPrefs() {
    /* 穿透：卸掉旧 Flutter SW，避免首屏多等 4s 超时 */
    try {
      if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
        navigator.serviceWorker.getRegistrations().then(function (regs) {
          regs.forEach(function (r) {
            r.unregister();
          });
        });
      }
    } catch (e) {}

    /* 每次加载强制品牌色与深色，避免旧紫种 / 系统色残留 */
    setJson("theme_mode", '"dark"');
    setJson("primary_color", GOLD_STR);
    setJson("chat.fluffy.color_scheme_seed", GOLD_STR);
    try {
      localStorage.setItem("jingepi_fluffy_theme_ver", THEME_VER);
    } catch (e) {}
  }

  function syncHomeserverFromConfig() {
    fetch("config.json", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (cfg) {
        if (!cfg || typeof cfg.defaultHomeserver !== "string") return;
        var hs = cfg.defaultHomeserver.replace(/\/+$/, "");
        if (!hs) return;
        setJson("chat.fluffy.default_homeserver", JSON.stringify(hs));
        try {
          localStorage.setItem("jingepi_public_base", hs);
        } catch (e) {}
      })
      .catch(function () {});
  }

  function markReady() {
    try {
      document.body.classList.add("jingepi-fluffy-ready");
    } catch (e) {}
  }

  function watchFlutterReady() {
    if (!document.body) return;
    if (
      document.querySelector("flutter-view") ||
      document.querySelector("flt-glass-pane") ||
      document.querySelector("canvas")
    ) {
      markReady();
      return;
    }
    var obs = new MutationObserver(function () {
      if (
        document.querySelector("flutter-view") ||
        document.querySelector("flt-glass-pane") ||
        document.querySelector("canvas")
      ) {
        markReady();
        obs.disconnect();
      }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true });
  }

  function clearMatrixSessionLocal() {
    if (window.JingepiMatrixLogout && window.JingepiMatrixLogout.clearMatrixSession) {
      return window.JingepiMatrixLogout.clearMatrixSession();
    }
    return Promise.resolve();
  }

  try {
    window.jingepiClearMatrixSession = clearMatrixSessionLocal;
  } catch (e) {}

  try {
    window.addEventListener("message", function (ev) {
      if (!ev || !ev.data) return;
      var data = ev.data;
      if (data === "jingepi-logout" || (data && data.type === "jingepi-logout")) {
        clearMatrixSessionLocal();
      }
    });
  } catch (e) {}

  lockBrandPrefs();
  syncHomeserverNow();
  syncHomeserverFromConfig();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watchFlutterReady);
  } else {
    watchFlutterReady();
  }

  /* 文档标题品牌化（不依赖 Flutter 异步改 title） */
  try {
    if (!/金格/.test(document.title || "")) {
      document.title = "金格Pi聊天室";
    }
  } catch (e) {}
})();
