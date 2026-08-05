/**
 * 实训环境注入（Element nginx sub_filter）：
 * 1) 隐藏「验证此设备 / 恢复密钥 / 密钥存储 / 备份」类 Toast / Banner
 * 2) 隐藏设置页中的加密 / 密钥存储 / 安全备份 / 恢复 / 密码学整段 UI
 * 3) 隐藏设置页 MXID（保留显示名）
 * 4) 隐藏房间加密开关等仍可能露出的入口
 * 5) 隐藏「添加服务器 / Edit homeserver / Server picker」——
 *    disable_custom_urls 已锁登录切换；房间目录 NetworkDropdown 仍有 Add server，靠本脚本兜底
 * 6) 隐藏设置侧栏「实验室 / Labs」（show_labs_settings=false 的 UI 兜底）
 * 7) 强制主题「金格Pi」，隐藏外观页主题切换 / 匹配系统主题
 *
 * Element Web 1.12.x：无 config 可关 Encryption 设置页与 VERIFY_THIS_SESSION Toast；
 * 亦无 UIFeature.themeSetting，主题锁定靠 default_theme + 本脚本。
 */
(function () {
  var STYLE_ID = "jingepi-lab-e2ee-hide";
  var FORCED_THEME = "custom-金格Pi";

  var HIDE_CSS = [
    "/* ---- 设置页隐藏 MXID ---- */",
    ".mx_UserProfileSettings_profile_controls_userId,",
    ".mx_UserProfileSettings_profile_controls_userId_label {",
    "  display: none !important;",
    "}",
    ".mx_UserMenu .mx_CopyableText,",
    ".mx_UserMenu [data-testid='copyable-text'] {",
    "  display: none !important;",
    "}",

    "/* ---- Encryption 设置整页 / 面板 ---- */",
    ".mx_EncryptionUserSettingsTab,",
    ".mx_KeyStoragePanel_toggleRow,",
    ".mx_RecoveryPanelOutOfSync,",
    ".mx_ChangeRecoveryKey,",
    ".mx_ChangeRecoveryKey_Form,",
    ".mx_EncryptionCard,",
    ".mx_EncryptionDetails,",
    ".mx_EncryptionInfo_spinner,",
    ".mx_SetupEncryptionBody,",
    ".mx_CompleteSecurityBody,",
    ".mx_CompleteSecurity_body,",
    ".mx_CompleteSecurity_header,",
    ".mx_CompleteSecurity_actionRow,",
    ".mx_Crypto {",
    "  display: none !important;",
    "}",

    "/* ---- 密钥备份 / SSSS / 交叉签名对话框 ---- */",
    ".mx_ConfirmKeyStorageOffDialog,",
    ".mx_CreateCrossSigningDialog,",
    ".mx_CreateSecretStorageDialog,",
    ".mx_AccessSecretStorageDialog,",
    ".mx_RestoreKeyBackupDialog,",
    ".mx_KeyBackupFailedDialog,",
    ".mx_CreateSecretStorageDialog_recoveryKey,",
    ".mx_AccessSecretStorageDialog_recoveryKeyEntry {",
    "  display: none !important;",
    "}",

    "/* ---- Toast 容器被标记后强制隐藏 ---- */",
    ".mx_ToastContainer[data-jingepi-e2ee-nag='1'],",
    ".mx_Banner[data-jingepi-e2ee-nag='1'],",
    "[role='alert'][data-jingepi-e2ee-nag='1'] {",
    "  display: none !important;",
    "}",

    "/* ---- 设置侧栏：Encryption / Labs 标签（由 JS 打标） ---- */",
    ".mx_TabbedView_tabLabel[data-jingepi-hide-e2ee='1'],",
    ".mx_TabbedView_tabPanel[data-jingepi-hide-e2ee='1'],",
    ".mx_TabbedView_tabLabel[data-jingepi-hide-labs='1'],",
    ".mx_TabbedView_tabPanel[data-jingepi-hide-labs='1'] {",
    "  display: none !important;",
    "}",

    "/* ---- 设置内按标题隐藏区块（由 JS 打标） ---- */",
    "[data-jingepi-hide-e2ee-section='1'] {",
    "  display: none !important;",
    "}",

    "/* ---- 房间设置 / 创建房间：加密开关 ---- */",
    ".mx_SettingsFlag[data-jingepi-hide-e2ee='1'],",
    "label[data-jingepi-hide-e2ee='1'],",
    ".mx_Dialog [data-jingepi-hide-e2ee='1'] {",
    "  display: none !important;",
    "}",

    "/* ---- 禁止换/加 homeserver（登录 ServerPicker + 房间目录 Add server） ---- */",
    ".mx_ServerPicker_change,",
    ".mx_ServerPicker_help,",
    ".mx_ServerPickerDialog,",
    ".mx_ServerPicker_helpDialog,",
    ".mx_NetworkDropdown_dialog,",
    "[data-jingepi-hide-server='1'] {",
    "  display: none !important;",
    "}",

    "/* ---- 强制金格Pi主题：隐藏 Appearance 主题选择器 ---- */",
    ".mx_ThemeChoicePanel_ThemeSelectors,",
    ".mx_ThemeChoicePanel_themeSelector,",
    ".mx_ThemeChoicePanel_CustomTheme,",
    ".mx_ThemeChoicePanel_CustomThemeList,",
    "[data-jingepi-hide-theme='1'] {",
    "  display: none !important;",
    "}",
  ].join("\n");

  function injectCss() {
    if (document.getElementById(STYLE_ID)) return;
    var style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = HIDE_CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  /* ---- Toast / Banner 文案 ---- */
  var NAG_RE =
    /验证此设备|验证此会话|Verify this device|Verify this session|Back up your chats|备份聊天|密钥存储|key storage|Turn on key storage|开启密钥存储|Allow key storage|允许密钥存储|out of sync|不同步|identity|数字身份|recovery key|恢复密钥|Secure Backup|安全备份|端到端加密自动备份|自动备份|Cryptography|密码学|Set up recovery|设置恢复|Forgot recovery|忘记恢复/i;

  var TAB_RE = /^(加密|Encryption)$/i;
  var LABS_TAB_RE = /^(实验室|Labs)$/i;
  var SECTION_HEAD_RE =
    /^(密钥存储|Key storage|安全备份|Secure Backup|备份|Backup|恢复|Recovery|密码学|Cryptography|加密|Encryption|端到端加密|End-to-end encryption|允许密钥存储|Allow key storage)$/i;
  var ROOM_ENCRYPT_RE =
    /启用加密|Enable encryption|端到端加密|End-to-end encryption|加密此房间|Encrypt this room/i;

  /* 登录「编辑」homeserver、房间目录「添加服务器」、设置里换服相关 */
  var ADD_SERVER_RE =
    /添加服务器|添加新服务器|添加一个服务器|添加其它服务器|切换服务器|更换服务器|更改服务器|编辑服务器|Add a server|Add server|Add new server|Add another server|Change server|Edit server|Other homeserver|其它服务器|其他服务器|自定义服务器|Custom server/i;

  /* 外观页内：主题选择、匹配系统主题（勿匹配整页「外观/Appearance」标题） */
  var THEME_SECTION_RE =
    /^(主题|Theme|匹配系统主题|Match system theme|跟随系统主题|Use system theme|自定义主题|Custom themes?)$/i;
  var THEME_MENU_RE =
    /^(主题|Theme|浅色|深色|Light|Dark|匹配系统主题|Match system theme)$/i;

  function forceJinGeTheme() {
    try {
      var raw = localStorage.getItem("mx_local_settings");
      var s = raw ? JSON.parse(raw) : {};
      if (typeof s !== "object" || s === null) s = {};
      var need =
        s.theme !== FORCED_THEME || s.use_system_theme === true || s.use_system_theme === "true";
      if (!need) return;
      s.theme = FORCED_THEME;
      s.use_system_theme = false;
      localStorage.setItem("mx_local_settings", JSON.stringify(s));
      if (!sessionStorage.getItem("jingepi_theme_forced_v1")) {
        sessionStorage.setItem("jingepi_theme_forced_v1", "1");
        location.reload();
      }
    } catch (_e) {
      /* ignore */
    }
  }

  function hideThemeSwitcher() {
    var nodes = document.querySelectorAll(
      ".mx_ThemeChoicePanel_ThemeSelectors, .mx_ThemeChoicePanel_CustomTheme"
    );
    for (var i = 0; i < nodes.length; i++) {
      var panel =
        nodes[i].closest(
          ".mx_SettingsSubsection, .mx_SettingsTab_section, section, form, div"
        ) || nodes[i];
      panel.setAttribute("data-jingepi-hide-theme", "1");
    }

    var headings = document.querySelectorAll(
      "h1, h2, h3, h4, .mx_SettingsSubsection_heading, .mx_SettingsTab_section_caption, .mx_SettingsTab_heading, label, [role='heading']"
    );
    for (var j = 0; j < headings.length; j++) {
      var h = headings[j];
      var text = (h.textContent || "").replace(/\s+/g, " ").trim();
      if (!THEME_SECTION_RE.test(text)) continue;
      var section =
        h.closest(
          ".mx_SettingsSubsection, .mx_ThemeChoicePanel_ThemeSelectors, .mx_SettingsFlag, form, label"
        ) || h.parentElement;
      if (section) {
        section.setAttribute("data-jingepi-hide-theme", "1");
      }
    }

    var menuItems = document.querySelectorAll(
      "[role='menuitem'], .mx_IconizedContextMenu_item, .mx_AccessibleButton"
    );
    for (var k = 0; k < menuItems.length; k++) {
      var el = menuItems[k];
      var t = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (THEME_MENU_RE.test(t)) {
        el.setAttribute("data-jingepi-hide-theme", "1");
      }
    }
  }

  function dismissListener() {
    try {
      var dl = window.mxDeviceListener;
      if (dl && typeof dl.dismissEncryptionSetup === "function") {
        dl.dismissEncryptionSetup();
      }
    } catch (_e) {
      /* ignore */
    }
  }

  function markNag(el) {
    if (!el) return;
    var text = el.textContent || "";
    if (!text.trim()) return;
    if (NAG_RE.test(text)) {
      dismissListener();
      el.setAttribute("data-jingepi-e2ee-nag", "1");
    } else if (el.getAttribute("data-jingepi-e2ee-nag") === "1") {
      el.removeAttribute("data-jingepi-e2ee-nag");
    }
  }

  function suppressToasts() {
    markNag(document.querySelector(".mx_ToastContainer"));
    var banners = document.querySelectorAll(
      ".mx_Banner, [role='alert'], .mx_InfoTooltip, .mx_Toast_toast"
    );
    for (var i = 0; i < banners.length; i++) {
      markNag(banners[i]);
    }
  }

  function hideEncryptionTabs() {
    var labels = document.querySelectorAll(
      ".mx_TabbedView_tabLabel, .mx_TabbedView_tabLabel_text"
    );
    for (var i = 0; i < labels.length; i++) {
      var el = labels[i];
      var text = (el.textContent || "").replace(/\s+/g, " ").trim();
      var tab =
        el.classList.contains("mx_TabbedView_tabLabel")
          ? el
          : el.closest(".mx_TabbedView_tabLabel");
      if (!tab) continue;
      if (TAB_RE.test(text)) {
        tab.setAttribute("data-jingepi-hide-e2ee", "1");
      } else if (LABS_TAB_RE.test(text)) {
        tab.setAttribute("data-jingepi-hide-labs", "1");
      }
    }
  }

  function hideSectionsByHeading() {
    var headings = document.querySelectorAll(
      "h1, h2, h3, h4, .mx_SettingsTab_section_caption, .mx_SettingsSubsection_heading, .mx_SettingsTab_heading, [role='heading']"
    );
    for (var i = 0; i < headings.length; i++) {
      var h = headings[i];
      var text = (h.textContent || "").replace(/\s+/g, " ").trim();
      if (!SECTION_HEAD_RE.test(text) && !NAG_RE.test(text)) continue;
      var section =
        h.closest(
          ".mx_SettingsTab_section, .mx_SettingsSubsection, .mx_SettingsTab_sections > *, .mx_EncryptionCard, section, article"
        ) || h.parentElement;
      if (section) {
        section.setAttribute("data-jingepi-hide-e2ee-section", "1");
      }
    }
  }

  function hideRoomEncryptionToggles() {
    var nodes = document.querySelectorAll(
      "label, .mx_SettingsFlag, .mx_ToggleControl, .mx_StyledRadioButton, .mx_Dialog label"
    );
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var text = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (ROOM_ENCRYPT_RE.test(text)) {
        var wrap =
          el.closest(".mx_SettingsFlag, .mx_SettingsTab_section, label, div") ||
          el;
        wrap.setAttribute("data-jingepi-hide-e2ee", "1");
      }
    }
  }

  function hideAddServerUi() {
    var nodes = document.querySelectorAll(
      "button, a, [role='button'], [role='menuitem'], [role='option'], .mx_AccessibleButton, .mx_MenuItem, li, .mx_Dialog"
    );
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var text = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (!text || text.length > 80) continue;
      if (!ADD_SERVER_RE.test(text)) continue;
      var wrap =
        el.closest(
          ".mx_Dialog, .mx_NetworkDropdown_dialog, .mx_ServerPickerDialog, [role='menuitem'], [role='option'], .mx_AccessibleButton, button, a, li, div"
        ) || el;
      wrap.setAttribute("data-jingepi-hide-server", "1");
    }

    /* ServerPicker「编辑」按钮（disable_custom_urls 失效时的兜底） */
    var changes = document.querySelectorAll(
      ".mx_ServerPicker_change, .mx_ServerPicker .mx_AccessibleButton"
    );
    for (var j = 0; j < changes.length; j++) {
      var btn = changes[j];
      var t = (btn.textContent || "").replace(/\s+/g, " ").trim();
      if (/^(编辑|Edit|更改|Change)$/i.test(t) || ADD_SERVER_RE.test(t)) {
        btn.setAttribute("data-jingepi-hide-server", "1");
      }
    }
  }

  function suppress() {
    suppressToasts();
    hideEncryptionTabs();
    hideSectionsByHeading();
    hideRoomEncryptionToggles();
    hideAddServerUi();
    hideThemeSwitcher();
  }

  var obs = new MutationObserver(suppress);

  function start() {
    forceJinGeTheme();
    injectCss();
    obs.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    setInterval(suppress, 1500);
    suppress();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
