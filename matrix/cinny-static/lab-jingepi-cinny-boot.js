/**
 * 金格Pi × Cinny 启动引导（内联进 HTML，零额外请求）
 * 须在 Cinny module 之前执行：locale / 深色 / SSO 路由 / API 预热
 */
(function () {
  var origin = window.location.origin.replace(/\/$/, "");

  try {
    localStorage.setItem("i18nextLng", "zh-CN");
    var s = {};
    try {
      s = JSON.parse(localStorage.getItem("settings") || "{}") || {};
    } catch (e0) {
      s = {};
    }
    s.useSystemTheme = false;
    s.themeId = "dark-theme";
    s.darkThemeId = "dark-theme";
    localStorage.setItem("settings", JSON.stringify(s));
    document.documentElement.setAttribute("lang", "zh-CN");
    document.documentElement.setAttribute("data-theme", "dark");
    document.documentElement.setAttribute("data-jingepi-theme", "1");
    document.documentElement.style.colorScheme = "dark";
  } catch (e1) {
    /* ignore */
  }

  function sameOriginHs(url) {
    if (!url || typeof url !== "string") return false;
    try {
      return new URL(url, origin).origin === origin;
    } catch (e) {
      return false;
    }
  }

  try {
    var savedHs = localStorage.getItem("cinny_hs_base_url");
    if (savedHs && !sameOriginHs(savedHs)) {
      localStorage.removeItem("cinny_hs_base_url");
      localStorage.removeItem("cinny_access_token");
      localStorage.removeItem("cinny_device_id");
      localStorage.removeItem("cinny_user_id");
    }
  } catch (e2) {
    /* ignore */
  }

  var hasLoginToken = /(?:^|[?&])loginToken=/.test(window.location.search || "");
  if (!hasLoginToken) {
    try {
      var hash = window.location.hash || "";
      var m = hash.match(/^#\/(login|register|reset-password)\/([^/?#]*)(.*)$/i);
      if (m && m[2]) {
        var decoded = m[2];
        try {
          decoded = decodeURIComponent(m[2]);
        } catch (e3) {
          /* keep */
        }
        if (!sameOriginHs(decoded)) {
          history.replaceState(
            null,
            "",
            window.location.pathname +
              window.location.search +
              "#/" +
              m[1] +
              "/" +
              encodeURIComponent(origin) +
              (m[3] || "")
          );
        }
      }
    } catch (e4) {
      /* ignore */
    }
  }

  try {
    fetch("/_matrix/client/versions", { credentials: "same-origin" });
    fetch("/.well-known/matrix/client", { credentials: "same-origin" });
    fetch("config.json", { credentials: "same-origin" });
  } catch (e5) {
    /* ignore */
  }
})();
