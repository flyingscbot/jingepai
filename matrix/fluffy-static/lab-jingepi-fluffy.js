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

  function lockBrandPrefs() {
    /* 每次加载强制品牌色与深色，避免旧紫种 / 系统色残留 */
    setJson("theme_mode", '"dark"');
    setJson("primary_color", GOLD_STR);
    setJson("chat.fluffy.color_scheme_seed", GOLD_STR);
    try {
      localStorage.setItem("jingepi_fluffy_theme_ver", THEME_VER);
    } catch (e) {}
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
    setTimeout(function () {
      markReady();
      try {
        obs.disconnect();
      } catch (e) {}
    }, 8000);
  }

  lockBrandPrefs();

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
