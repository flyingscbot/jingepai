/**
 * 金格Pi × Cinny — 延后汉化（defer，不挡主 bundle 下载/解析）
 */
(function () {
  var ZH_EXACT = {
    "Heating up": "正在连接…",
    "Continue with SSO": "使用 SSO 继续",
    "Continue with Password": "使用密码继续",
    "Welcome to Cinny": "欢迎使用金格Pi 聊天",
    "Connection Lost!": "连接已断开！",
    "Something went wrong": "出了点问题",
    Homeserver: "服务器",
    Username: "用户名",
    Password: "密码",
    Login: "登录",
    Settings: "设置",
    Logout: "退出登录",
    Search: "搜索",
    Home: "主页",
    People: "联系人",
    Rooms: "房间",
    Connecting: "连接中",
    Syncing: "同步中",
    Connected: "已连接",
    Retry: "重试",
    Cancel: "取消",
    Send: "发送",
    "Send a message...": "发送消息",
  };

  var ZH_PLACEHOLDER = {
    Search: "搜索",
    Username: "用户名",
    Password: "密码",
    Homeserver: "服务器",
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

  function markBody() {
    try {
      if (!document.body) return;
      document.body.setAttribute("data-theme", "dark");
      document.body.classList.add("jingepi-cinny-ready");
      document.body.style.colorScheme = "dark";
    } catch (e) {
      /* ignore */
    }
  }

  function startZhChrome() {
    var scheduled = false;
    var stopped = false;

    function run() {
      if (stopped) return;
      scheduled = false;
      markBody();
      try {
        if (document.body) walkTranslate(document.body);
      } catch (e) {
        /* ignore */
      }
    }

    function schedule() {
      if (stopped || scheduled) return;
      scheduled = true;
      setTimeout(run, 500);
    }

    function boot() {
      run();
      var mo;
      try {
        mo = new MutationObserver(schedule);
        mo.observe(document.body || document.documentElement, {
          childList: true,
          subtree: true,
        });
      } catch (e3) {
        /* ignore */
      }
      setTimeout(function () {
        stopped = true;
        if (mo) {
          try {
            mo.disconnect();
          } catch (e4) {
            /* ignore */
          }
        }
      }, 20000);
    }

    if (document.body) boot();
    else document.addEventListener("DOMContentLoaded", boot);
  }

  if (window.requestIdleCallback) {
    window.requestIdleCallback(startZhChrome, { timeout: 2000 });
  } else {
    window.addEventListener("load", function () {
      setTimeout(startZhChrome, 300);
    });
  }
})();
