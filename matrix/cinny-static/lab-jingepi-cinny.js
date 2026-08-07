/**
 * 金格Pi × Cinny — 安全注入（深色 + 中文默认 + 同源 HS）
 *
 * 故障修复（2026-08）：去掉 Storage.prototype 拦截、去掉与 React 抢 class 的
 * MutationObserver、去掉 characterData 全文汉化（曾导致卡死/白屏进不去）。
 *
 * 保留：
 * 1) 启动时写 settings → dark-theme（覆盖旧 light/system，只写一次/启动）
 * 2) 启动时写 i18nextLng=zh-CN（强制默认中文；不拦截后续 setItem）
 * 3) CSS 负责锁深色外观；此处只做轻量 data-theme / colorScheme
 * 4) config HS 同源、SSO loginToken 不改 hash、陈旧会话清理
 * 5) 保守 DOM 汉化（仅 childList、精确词表、低频）
 */
(function () {
  var origin = window.location.origin.replace(/\/$/, "");
  var LOCALE_KEY = "i18nextLng";
  var SETTINGS_KEY = "settings";
  var DEFAULT_LOCALE = "zh-CN";

  function sameOriginHs(url) {
    if (!url || typeof url !== "string") return false;
    try {
      return new URL(url, origin).origin === origin;
    } catch (e) {
      return false;
    }
  }

  function forceConfig(cfg) {
    if (!cfg || typeof cfg !== "object") return cfg;
    var list = Array.isArray(cfg.homeserverList) ? cfg.homeserverList.slice() : [];
    var others = [];
    for (var i = 0; i < list.length; i++) {
      var item = typeof list[i] === "string" ? list[i].trim().replace(/\/$/, "") : "";
      if (item && item !== origin && others.indexOf(item) === -1) others.push(item);
    }
    cfg.homeserverList = [origin].concat(others);
    cfg.defaultHomeserver = 0;
    if (!cfg.hashRouter || typeof cfg.hashRouter !== "object") cfg.hashRouter = {};
    cfg.hashRouter.enabled = true;
    if (!cfg.hashRouter.basename) cfg.hashRouter.basename = "/";
    return cfg;
  }

  function clearMatrixSession() {
    try {
      localStorage.removeItem("cinny_hs_base_url");
      localStorage.removeItem("cinny_access_token");
      localStorage.removeItem("cinny_device_id");
      localStorage.removeItem("cinny_user_id");
    } catch (e) {
      /* ignore */
    }
  }

  /** 启动时写深色 settings（合并已有键，不拦截后续写入） */
  function applyDarkSettingsOnce() {
    try {
      var s = {};
      var raw = localStorage.getItem(SETTINGS_KEY);
      if (raw) {
        try {
          s = JSON.parse(raw) || {};
        } catch (e) {
          s = {};
        }
      }
      s.useSystemTheme = false;
      s.themeId = "dark-theme";
      s.darkThemeId = "dark-theme";
      if (!s.lightThemeId) s.lightThemeId = "light-theme";
      s.monochromeMode = false;
      if (s.hour24Clock === undefined) s.hour24Clock = true;
      if (!s.dateFormatString) s.dateFormatString = "YYYY-MM-DD";
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
    } catch (e2) {
      /* ignore */
    }
  }

  /** 启动时强制简中（不 hook setItem） */
  function applyLocaleOnce() {
    try {
      localStorage.setItem(LOCALE_KEY, DEFAULT_LOCALE);
      document.documentElement.setAttribute("lang", "zh-CN");
    } catch (e) {
      try {
        document.documentElement.setAttribute("lang", "zh-CN");
      } catch (e2) {
        /* ignore */
      }
    }
  }

  function markDarkDom() {
    try {
      document.documentElement.setAttribute("data-theme", "dark");
      document.documentElement.setAttribute("data-jingepi-theme", "1");
      document.documentElement.style.colorScheme = "dark";
      function onBody() {
        if (!document.body) return;
        document.body.setAttribute("data-theme", "dark");
        document.body.classList.add("jingepi-cinny-ready");
        document.body.style.colorScheme = "dark";
      }
      if (document.body) onBody();
      else document.addEventListener("DOMContentLoaded", onBody);
    } catch (e) {
      /* ignore */
    }
  }

  // —— 保守汉化（多词/明确 UI；不观察 characterData，避免与 React 互殴）——
  var ZH_EXACT = {
    "Continue with SSO": "使用 SSO 继续",
    "Continue with Password": "使用密码继续",
    "Welcome to Cinny": "欢迎使用金格Pi 聊天",
    "Confirm Password": "确认密码",
    "Display Name": "显示名称",
    "User Settings": "用户设置",
    "Room Settings": "房间设置",
    "Space Settings": "空间设置",
    "Create Room": "创建房间",
    "Create Space": "创建空间",
    "Join Room": "加入房间",
    "Leave Room": "离开房间",
    "Direct Messages": "私信",
    "Direct Message": "私信",
    "Mark as Read": "标为已读",
    "Search Messages": "搜索消息",
    "Clear Cache and Reload": "清除缓存并重新加载",
    "Clear Cache": "清除缓存",
    "Developer Tools": "开发者工具",
    "Message Layout": "消息布局",
    "Message Spacing": "消息间距",
    "Media Auto Load": "自动加载媒体",
    "System Theme": "跟随系统",
    "Use System Theme": "跟随系统",
    "Jump to Latest": "跳到最新",
    "Apply Changes": "应用更改",
    "More Options": "更多选项",
    "Enable Encryption": "启用加密",
    "Power Levels": "权限等级",
    "Pinned Messages": "置顶消息",
    "Reply in Thread": "在话题中回复",
    "Connection Lost!": "连接已断开！",
    "Something went wrong": "出了点问题",
    "No rooms": "暂无房间",
    "No results": "无结果",
    "Add Server": "添加服务器",
    "New Chat": "新聊天",
    "New Room": "新房间",
    "Send Message": "发送消息",
    "Copy Link": "复制链接",
    "View Source": "查看源码",
    "Date Format": "日期格式",
    "Page Zoom": "页面缩放",
    "Monochrome Mode": "单色模式",
    "Legacy Username Color": "传统用户名颜色",
    "Show Hidden Events": "显示隐藏事件",
    "Twitter Emoji": "Twitter 表情",
    Homeserver: "服务器",
    Username: "用户名",
    Password: "密码",
    Login: "登录",
    Register: "注册",
    Settings: "设置",
    Appearance: "外观",
    Notifications: "通知",
    Account: "账户",
    Devices: "设备",
    Encryption: "加密",
    About: "关于",
    Logout: "退出登录",
    Search: "搜索",
    Inbox: "收件箱",
    Home: "主页",
    People: "联系人",
    Rooms: "房间",
    Spaces: "空间",
    Explore: "探索",
    Members: "成员",
    Files: "文件",
    Invite: "邀请",
    Cancel: "取消",
    Confirm: "确认",
    Save: "保存",
    Close: "关闭",
    Back: "返回",
    Next: "下一步",
    Send: "发送",
    Reply: "回复",
    Edit: "编辑",
    Delete: "删除",
    Copy: "复制",
    Dark: "深色",
    Light: "浅色",
    Butter: "黄油",
    Silver: "银色",
    General: "通用",
    Profile: "个人资料",
    Online: "在线",
    Offline: "离线",
    Connecting: "连接中",
    Syncing: "同步中",
    Connected: "已连接",
    Retry: "重试",
    Refresh: "刷新",
    Reload: "重新加载",
    Upload: "上传",
    Download: "下载",
    Accept: "接受",
    Decline: "拒绝",
    Unread: "未读",
    Mentions: "提及",
    Invites: "邀请",
    Filter: "筛选",
    All: "全部",
  };

  var ZH_PLACEHOLDER = {
    Search: "搜索",
    "Search messages": "搜索消息",
    "Search Messages": "搜索消息",
    Username: "用户名",
    Password: "密码",
    Homeserver: "服务器",
    "Display Name": "显示名称",
  };

  function translateTextNode(node) {
    if (!node || node.nodeType !== 3) return;
    var raw = node.nodeValue;
    if (raw == null) return;
    var trimmed = raw.replace(/^\s+|\s+$/g, "");
    if (!trimmed || trimmed.length > 64) return;
    if (/^[@#!].*:/.test(trimmed)) return;
    if (/^[\u4e00-\u9fff]/.test(trimmed)) return;
    var zh = ZH_EXACT[trimmed];
    if (!zh) return;
    var lead = raw.match(/^\s*/);
    var trail = raw.match(/\s*$/);
    node.nodeValue = (lead ? lead[0] : "") + zh + (trail ? trail[0] : "");
  }

  function translateAttrs(el) {
    if (!el || el.nodeType !== 1) return;
    var attrs = ["placeholder", "aria-label", "title"];
    for (var i = 0; i < attrs.length; i++) {
      var a = attrs[i];
      if (!el.hasAttribute(a)) continue;
      var v = el.getAttribute(a);
      var mapped = ZH_PLACEHOLDER[v] || ZH_EXACT[v];
      if (mapped && mapped !== v) el.setAttribute(a, mapped);
    }
  }

  function walkTranslate(root) {
    if (!root || root.nodeType !== 1) return;
    var skip = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, CODE: 1, PRE: 1, NOSCRIPT: 1, INPUT: 1 };
    try {
      translateAttrs(root);
      var marked = root.querySelectorAll("[placeholder],[aria-label],[title]");
      for (var i = 0; i < marked.length; i++) translateAttrs(marked[i]);
    } catch (e0) {
      /* ignore */
    }
    try {
      var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode: function (n) {
          var p = n.parentElement;
          if (!p || skip[p.tagName] || p.isContentEditable) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        },
      });
      var n;
      while ((n = walker.nextNode())) translateTextNode(n);
    } catch (e1) {
      /* ignore */
    }
  }

  function startZhChrome() {
    var scheduled = false;
    var passes = 0;
    function run() {
      scheduled = false;
      passes += 1;
      try {
        if (document.body) walkTranslate(document.body);
      } catch (e) {
        /* ignore */
      }
    }
    function schedule() {
      if (passes > 80) return; // 防止长时间互殴
      if (scheduled) return;
      scheduled = true;
      setTimeout(run, 200);
    }
    function boot() {
      run();
      // 仅观察子树结构变化，不观察 characterData / class
      try {
        var mo = new MutationObserver(schedule);
        mo.observe(document.body || document.documentElement, {
          childList: true,
          subtree: true,
        });
        // 30s 后停掉观察，避免长期开销
        setTimeout(function () {
          try {
            mo.disconnect();
          } catch (e2) {
            /* ignore */
          }
        }, 30000);
      } catch (e3) {
        /* ignore */
      }
    }
    if (document.body) boot();
    else document.addEventListener("DOMContentLoaded", boot);
  }

  // —— HS / SW / SSO / config ——
  try {
    var savedHs = localStorage.getItem("cinny_hs_base_url");
    if (savedHs && !sameOriginHs(savedHs)) clearMatrixSession();
  } catch (e) {
    /* ignore */
  }

  try {
    if (navigator.serviceWorker) {
      navigator.serviceWorker.getRegistrations().then(function (regs) {
        for (var i = 0; i < regs.length; i++) regs[i].unregister();
      });
    }
  } catch (eSw) {
    /* ignore */
  }

  var search = "";
  try {
    search = window.location.search || "";
  } catch (e0) {
    /* ignore */
  }
  var hasLoginToken = /(?:^|[?&])loginToken=/.test(search);

  if (!hasLoginToken) {
    try {
      var hash = window.location.hash || "";
      var m = hash.match(/^#\/(login|register|reset-password)\/([^/?#]*)(.*)$/i);
      if (m) {
        var kind = m[1];
        var serverPart = m[2];
        var rest = m[3] || "";
        var decoded = serverPart;
        try {
          decoded = decodeURIComponent(serverPart);
        } catch (e2) {
          /* keep */
        }
        if (serverPart && !sameOriginHs(decoded)) {
          history.replaceState(
            null,
            "",
            window.location.pathname +
              window.location.search +
              "#/" +
              kind +
              "/" +
              encodeURIComponent(origin) +
              rest
          );
        }
      }
    } catch (e3) {
      /* ignore */
    }
  }

  try {
    var origFetch = window.fetch;
    if (typeof origFetch === "function") {
      window.fetch = function (input, init) {
        var url = "";
        try {
          if (typeof input === "string") url = input;
          else if (input && typeof input.url === "string") url = input.url;
        } catch (e4) {
          /* ignore */
        }
        var req = origFetch.apply(this, arguments);
        if (!/config\.json(?:\?|$)/i.test(url)) return req;
        return req.then(function (res) {
          if (!res || !res.ok) return res;
          return res
            .clone()
            .json()
            .then(function (cfg) {
              return new Response(JSON.stringify(forceConfig(cfg)), {
                status: res.status,
                statusText: res.statusText,
                headers: { "Content-Type": "application/json" },
              });
            })
            .catch(function () {
              return res;
            });
        });
      };
    }
  } catch (e5) {
    /* ignore */
  }

  // 启动（须在 Cinny module 读 localStorage 前）
  try {
    applyLocaleOnce();
    applyDarkSettingsOnce();
    markDarkDom();
  } catch (e6) {
    try {
      markDarkDom();
    } catch (e7) {
      /* ignore */
    }
  }

  // 启动后再补写一次，防止 Cinny 初始化过程中写回 light
  function reinforceOnce() {
    applyDarkSettingsOnce();
    applyLocaleOnce();
    markDarkDom();
  }
  setTimeout(reinforceOnce, 0);
  setTimeout(reinforceOnce, 500);
  setTimeout(reinforceOnce, 2000);

  startZhChrome();
})();
