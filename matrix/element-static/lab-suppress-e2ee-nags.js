/**
 * 实训环境注入（Element nginx sub_filter）：
 * 1) 隐藏「验证此设备 / 恢复密钥 / 密钥存储 / 备份」类 Toast / Banner
 * 2) 隐藏设置页中的加密 / 密钥存储 / 安全备份 / 恢复 / 密码学整段 UI
 * 3) 隐藏设置页 MXID / 显示名称；隐藏改头像入口（显示名与头像由金格同步）
 * 4) 隐藏房间加密开关等仍可能露出的入口
 * 5) 隐藏「添加服务器 / Edit homeserver / Server picker」——
 *    disable_custom_urls 已锁登录切换；房间目录 NetworkDropdown 仍有 Add server，靠本脚本兜底
 * 6) 隐藏设置侧栏「实验室 / Labs」（show_labs_settings=false 的 UI 兜底）
 * 7) 强制主题「金格Pi」，隐藏外观页主题切换 / 匹配系统主题
 * 8) 强制强调色 / CTA 为金格金（主按钮填色 #e0a80a，覆盖 Element / Compound 默认绿）
 * 9) 确保 lab-jingepi-theme.css 已加载（nginx 注入兜底；表面/字体以该 CSS 为主）
 *
 * Element Web 1.12.x：无 config 可关 Encryption 设置页与 VERIFY_THIS_SESSION Toast；
 * 亦无 UIFeature.themeSetting，主题锁定靠 default_theme + 本脚本。
 * Synapse enable_set_avatar_url=false + 本脚本隐藏上传控件；金格改头像走 Admin API。
 * 10) 普通用户隐藏「新建房间 / 创建空间」入口（权限由 /api/matrix/capabilities +
 *     matrix_proxy 拦截 createRoom；私聊 DM 仍允许）
 */
(function () {
  var STYLE_ID = "jingepi-lab-e2ee-hide";
  var THEME_LINK_ID = "jingepi-lab-theme-css";
  var THEME_VARS_LINK_ID = "jingepi-lab-theme-vars-css";
  var FORCED_THEME = "custom-金格Pi";
  /* 跟随 jingepi-theme-vars.css（管理后台可改）；硬编码仅作 getComputedStyle 回退 */
  var GOLD = "var(--jingepi-gold, #f0b90b)";
  var GOLD_BTN = "var(--jingepi-btn, #e0a80a)";
  var GOLD_HOVER = "var(--jingepi-btn-hover, #c99400)";
  var GOLD_PRESSED = "var(--jingepi-gold-deep, #c99400)";
  var GOLD_ON = "var(--jingepi-gold-on, #fff6d1)";
  var SURFACE = "var(--jingepi-surface, #12151c)";
  var PANEL = "var(--jingepi-panel, #12151c)";
  var PANEL_RAISED = "var(--jingepi-panel-raised, #12151c)";
  var INPUT = "var(--jingepi-input, #161a22)";
  var HIGHLIGHT = "var(--jingepi-highlight, #241c0e)";
  var TEXT = "var(--jingepi-text, #f5f5f5)";
  var TEXT_MUTED = "var(--jingepi-text-muted, #aaaaaa)";
  var BORDER = "rgba(255, 255, 255, 0.06)";
  var GOLD_LIGHT = "var(--jingepi-gold-light, #fcd535)";
  var GOLD_STOP4 = "var(--jingepi-gold-stop4, #a67c00)";

  /* null=未知；false=普通用户禁建群/空间；true=管理员 */
  var canCreateRooms = null;

  function resolvedColor(cssVar, fallback) {
    try {
      var v = getComputedStyle(document.documentElement)
        .getPropertyValue(cssVar)
        .trim();
      return v || fallback;
    } catch (e) {
      return fallback;
    }
  }

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

    "/* ---- 设置页隐藏「显示名称」整项（金格同步，用户不可见/不可改） ---- */",
    ".mx_UserProfileSettings_profile_displayName,",
    ".mx_UserProfileSettings_profile_controls_displayName,",
    ".mx_UserProfileSettings [data-testid='account-display-name'],",
    ".mx_UserProfileSettings [data-testid='displayname'],",
    ".mx_UserProfileSettings [data-testid='display-name'],",
    ".mx_AccountUserSettingsTab [data-testid='account-display-name'],",
    ".mx_SettingsSubsection[data-jingepi-hide-displayname='1'],",
    ".mx_Field[data-jingepi-hide-displayname='1'],",
    "[data-jingepi-hide-displayname='1'] {",
    "  display: none !important;",
    "  pointer-events: none !important;",
    "  height: 0 !important;",
    "  margin: 0 !important;",
    "  padding: 0 !important;",
    "  overflow: hidden !important;",
    "  border: 0 !important;",
    "}",

    "/* ---- 设置页隐藏改头像（金格为唯一来源） ---- */",
    ".mx_UserProfileSettings input[type='file'],",
    ".mx_AvatarSetting input[type='file'],",
    ".mx_AvatarSetting_upload,",
    ".mx_AvatarSetting_avatar .mx_AccessibleButton,",
    ".mx_UserProfileSettings_profile .mx_AccessibleButton[aria-label*='头像'],",
    ".mx_UserProfileSettings_profile .mx_AccessibleButton[aria-label*='Avatar'],",
    ".mx_UserProfileSettings_profile .mx_AccessibleButton[aria-label*='avatar'],",
    ".mx_UserProfileSettings_profile .mx_AccessibleButton[aria-label*='Upload'],",
    ".mx_UserProfileSettings_profile .mx_AccessibleButton[aria-label*='上传'] {",
    "  display: none !important;",
    "  pointer-events: none !important;",
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

    "/* ---- 普通用户：隐藏新建房间 / 创建空间 ---- */",
    "body[data-jingepi-no-create='1'] .mx_RoomListHeader_plusButton,",
    "body[data-jingepi-no-create='1'] .mx_RoomListHeader_plusMenuButton,",
    "body[data-jingepi-no-create='1'] [data-testid='room-list-options'],",
    "body[data-jingepi-no-create='1'] [data-jingepi-hide-create='1'] {",
    "  display: none !important;",
    "  pointer-events: none !important;",
    "}",

    "/* ---- 强制金格Pi主题：隐藏 Appearance 主题选择器 ---- */",
    ".mx_ThemeChoicePanel_ThemeSelectors,",
    ".mx_ThemeChoicePanel_themeSelector,",
    ".mx_ThemeChoicePanel_CustomTheme,",
    ".mx_ThemeChoicePanel_CustomThemeList,",
    "[data-jingepi-hide-theme='1'] {",
    "  display: none !important;",
    "}",

    "/* ---- 金格色板：绿 CTA + 炭灰/深蓝灰表面（与 lab-jingepi-theme.css 双保险） ---- */",
    ":root,",
    "html,",
    "body,",
    ".cpd-theme-dark,",
    ".cpd-theme-light,",
    "[class*='cpd-theme-'] {",
    "  --accent: " + GOLD_BTN + " !important;",
    "  --accent-color: " + GOLD_BTN + " !important;",
    "  --primary-color: " + GOLD_BTN + " !important;",
    "  --secondary-content: " + GOLD_PRESSED + " !important;",
    "  --tertiary-content: " + GOLD_LIGHT + " !important;",
    "  --background: " + SURFACE + " !important;",
    "  --cpd-color-text-action-accent: " + GOLD + " !important;",
    "  --cpd-color-icon-accent-tertiary: " + GOLD + " !important;",
    "  --cpd-color-icon-accent-primary: " + GOLD + " !important;",
    "  --cpd-color-bg-accent-rest: " + GOLD_BTN + " !important;",
    "  --cpd-color-bg-accent-hovered: " + GOLD_HOVER + " !important;",
    "  --cpd-color-bg-accent-pressed: " + GOLD_PRESSED + " !important;",
    "  --cpd-color-bg-accent-selected: rgba(240, 185, 11, 0.22) !important;",
    "  --cpd-color-bg-accent-subtle: rgba(240, 185, 11, 0.16) !important;",
    "  --cpd-color-bg-badge-accent: " + GOLD_LIGHT + " !important;",
    "  --cpd-color-text-badge-accent: " + GOLD_ON + " !important;",
    "  --cpd-color-border-accent-primary: " + GOLD + " !important;",
    "  --cpd-color-border-accent-subtle: " + GOLD_PRESSED + " !important;",
    "  --cpd-color-bg-action-primary-rest: " + GOLD_BTN + " !important;",
    "  --cpd-color-bg-action-primary-hovered: " + GOLD_HOVER + " !important;",
    "  --cpd-color-bg-action-primary-pressed: " + GOLD_PRESSED + " !important;",
    "  --cpd-color-text-on-solid-primary: " + GOLD_ON + " !important;",
    "  --cpd-color-icon-on-solid-primary: " + GOLD_ON + " !important;",
    "  --cpd-color-gradient-action-stop1: " + GOLD_BTN + " !important;",
    "  --cpd-color-gradient-action-stop2: " + GOLD_HOVER + " !important;",
    "  --cpd-color-gradient-action-stop3: " + GOLD_PRESSED + " !important;",
    "  --cpd-color-gradient-action-stop4: " + GOLD_STOP4 + " !important;",
    "  --cpd-color-bg-canvas-default: " + SURFACE + " !important;",
    "  --cpd-color-bg-subtle-primary: " + SURFACE + " !important;",
    "  --cpd-color-bg-subtle-secondary: " + SURFACE + " !important;",
    "  --cpd-color-bg-subtle-tertiary: " + SURFACE + " !important;",
    "  --cpd-color-text-primary: " + TEXT + " !important;",
    "  --cpd-color-text-secondary: " + TEXT_MUTED + " !important;",
    "  --cpd-color-separator-primary: " + BORDER + " !important;",
    "  --cpd-color-separator-secondary: rgba(255, 255, 255, 0.04) !important;",
    "  --cpd-color-border-focused: " + GOLD + " !important;",
    "  --cpd-color-text-link-external: " + GOLD_LIGHT + " !important;",
    "  --cpd-color-text-success-primary: " + GOLD + " !important;",
    "  --cpd-color-icon-success-primary: " + GOLD + " !important;",
    "  font-family: \"Noto Sans SC\", \"PingFang SC\", \"Microsoft YaHei\", \"Hiragino Sans GB\", sans-serif;",
    "}",

    ".mx_AccessibleButton_kind_primary,",
    ".mx_AccessibleButton.mx_AccessibleButton_kind_primary,",
    ".mx_Login_submit,",
    ".mx_Dialog_primary,",
    ".mx_Dialog button.mx_Dialog_primary,",
    ".mx_Dialog_buttons button.mx_Dialog_primary,",
    "button.mx_AccessibleButton_kind_primary,",
    ".cpd-button[data-kind='primary'],",
    "button[data-kind='primary'] {",
    "  background-color: " + GOLD_BTN + " !important;",
    "  background: " + GOLD_BTN + " !important;",
    "  border-color: " + GOLD_BTN + " !important;",
    "  color: " + GOLD_ON + " !important;",
    "  --cpd-color-text-on-solid-primary: " + GOLD_ON + " !important;",
    "  --cpd-color-icon-on-solid-primary: " + GOLD_ON + " !important;",
    "}",

    ".mx_AccessibleButton_kind_primary:hover,",
    ".mx_AccessibleButton.mx_AccessibleButton_kind_primary:hover,",
    ".mx_Login_submit:hover,",
    ".mx_Dialog_primary:hover,",
    ".cpd-button[data-kind='primary']:hover,",
    "button[data-kind='primary']:hover {",
    "  background-color: " + GOLD_HOVER + " !important;",
    "  background: " + GOLD_HOVER + " !important;",
    "  border-color: " + GOLD_HOVER + " !important;",
    "  color: " + GOLD_ON + " !important;",
    "}",

    ".mx_AccessibleButton_kind_primary:active,",
    ".mx_AccessibleButton.mx_AccessibleButton_kind_primary:active,",
    ".mx_Login_submit:active,",
    ".cpd-button[data-kind='primary']:active,",
    "button[data-kind='primary']:active {",
    "  background-color: " + GOLD_PRESSED + " !important;",
    "  background: " + GOLD_PRESSED + " !important;",
    "  border-color: " + GOLD_PRESSED + " !important;",
    "  color: " + GOLD_ON + " !important;",
    "}",

    ".mx_AccessibleButton_kind_primary svg,",
    ".mx_AccessibleButton.mx_AccessibleButton_kind_primary svg,",
    ".mx_Login_submit svg,",
    ".mx_Dialog_primary svg,",
    ".cpd-button[data-kind='primary'] svg,",
    "button[data-kind='primary'] svg,",
    ".mx_AccessibleButton_kind_primary svg path,",
    ".mx_AccessibleButton.mx_AccessibleButton_kind_primary svg path,",
    ".mx_Login_submit svg path,",
    ".mx_Dialog_primary svg path,",
    ".cpd-button[data-kind='primary'] svg path,",
    "button[data-kind='primary'] svg path {",
    "  color: " + GOLD_ON + " !important;",
    "  fill: currentColor !important;",
    "  stroke: currentColor;",
    "}",

    ".mx_AccessibleButton_kind_primary_outline,",
    ".mx_AccessibleButton_kind_primary_outline.mx_AccessibleButton {",
    "  color: " + GOLD + " !important;",
    "  border-color: " + GOLD + " !important;",
    "}",

    ".mx_AccessibleButton_kind_primary_outline:hover {",
    "  color: " + GOLD_HOVER + " !important;",
    "  border-color: " + GOLD_HOVER + " !important;",
    "  background-color: rgba(240, 185, 11, 0.12) !important;",
    "}",

    "a,",
    ".mx_TextButton,",
    ".mx_LinkButton,",
    ".mx_AccessibleButton_kind_link,",
    ".mx_AccessibleButton_kind_link_inline,",
    ".text-success {",
    "  --accent-color: " + GOLD + ";",
    "}",

    ".mx_AccessibleButton_kind_link,",
    ".mx_AccessibleButton_kind_link_inline,",
    ".mx_LinkButton,",
    ".mx_TextButton,",
    ".mx_LeftPanelLiveShareWarning,",
    ".mx_ShareType_badge,",
    "#mx_theme_accentColor {",
    "  color: " + GOLD + " !important;",
    "}",

    ".mx_LeftPanelLiveShareWarning,",
    ".mx_ShareType_badge {",
    "  background-color: " + GOLD + " !important;",
    "  color: " + GOLD_ON + " !important;",
    "}",
  ].join("\n");

  function forceGoldCssVars(el) {
    if (!el || !el.style || !el.style.setProperty) return;
    var pairs = [
      ["--accent", GOLD_BTN],
      ["--accent-color", GOLD_BTN],
      ["--primary-color", GOLD_BTN],
      ["--background", SURFACE],
      ["--cpd-color-text-action-accent", GOLD],
      ["--cpd-color-icon-accent-tertiary", GOLD],
      ["--cpd-color-icon-accent-primary", GOLD],
      ["--cpd-color-bg-accent-rest", GOLD_BTN],
      ["--cpd-color-bg-accent-hovered", GOLD_HOVER],
      ["--cpd-color-bg-accent-pressed", GOLD_PRESSED],
      ["--cpd-color-bg-action-primary-rest", GOLD_BTN],
      ["--cpd-color-bg-action-primary-hovered", GOLD_HOVER],
      ["--cpd-color-bg-action-primary-pressed", GOLD_PRESSED],
      ["--cpd-color-text-on-solid-primary", GOLD_ON],
      ["--cpd-color-icon-on-solid-primary", GOLD_ON],
      ["--cpd-color-border-accent-primary", GOLD],
      ["--cpd-color-bg-canvas-default", SURFACE],
      ["--cpd-color-bg-subtle-primary", SURFACE],
      ["--cpd-color-bg-subtle-secondary", SURFACE],
      ["--cpd-color-bg-subtle-tertiary", SURFACE],
      ["--cpd-color-text-primary", TEXT],
      ["--cpd-color-text-secondary", TEXT_MUTED],
      ["--cpd-color-separator-primary", BORDER],
      ["--cpd-color-border-focused", GOLD],
    ];
    for (var i = 0; i < pairs.length; i++) {
      el.style.setProperty(pairs[i][0], pairs[i][1], "important");
    }
  }

  function paintInlineGreens(root) {
    var goldHex = resolvedColor("--jingepi-gold", "#f0b90b");
    var pressedHex = resolvedColor("--jingepi-gold-deep", "#c99400");
    var nodes = (root || document).querySelectorAll
      ? (root || document).querySelectorAll("[style]")
      : [];
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var st = el.getAttribute("style") || "";
      if (
        !/#0[Dd][Bb][Dd]8[Bb]|#03[Bb]381|#00[Cc]073|#0[Ee][Cc][Dd]8[Cc]|#8[Ee]41[Ff]2|#7[Ee]57[Cc]2/i.test(
          st
        )
      ) {
        continue;
      }
      el.style.cssText = st
        .replace(/#0[Dd][Bb][Dd]8[Bb]/gi, goldHex)
        .replace(/#03[Bb]381/gi, goldHex)
        .replace(/#00[Cc]073/gi, goldHex)
        .replace(/#0[Ee][Cc][Dd]8[Cc]/gi, goldHex)
        .replace(/#8[Ee]41[Ff]2/gi, goldHex)
        .replace(/#7[Ee]57[Cc]2/gi, pressedHex);
    }
  }

  function ensureThemeStylesheet() {
    var head = document.head || document.documentElement;
    if (
      !document.getElementById(THEME_VARS_LINK_ID) &&
      !document.querySelector('link[href*="jingepi-theme-vars.css"]')
    ) {
      var vlink = document.createElement("link");
      vlink.id = THEME_VARS_LINK_ID;
      vlink.rel = "stylesheet";
      vlink.href = "jingepi-theme-vars.css";
      head.appendChild(vlink);
    }
    if (
      document.getElementById(THEME_LINK_ID) ||
      document.querySelector('link[href*="lab-jingepi-theme.css"]')
    ) {
      return;
    }
    var link = document.createElement("link");
    link.id = THEME_LINK_ID;
    link.rel = "stylesheet";
    link.href = "lab-jingepi-theme.css";
    head.appendChild(link);
  }

  function injectCss() {
    ensureThemeStylesheet();
    if (!document.getElementById(STYLE_ID)) {
      var style = document.createElement("style");
      style.id = STYLE_ID;
      style.textContent = HIDE_CSS;
      (document.head || document.documentElement).appendChild(style);
    }
    forceGoldCssVars(document.documentElement);
    forceGoldCssVars(document.body);
    paintInlineGreens(document);
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

  /* 新建群聊 / 空间（不含「开始私聊 / Start chat」） */
  var CREATE_ROOM_RE =
    /新建房间|创建房间|新建群聊|创建群聊|创建空间|新建空间|Explore rooms|Browse rooms|Create a? ?new room|Create room|New room|Create a? ?space|New space|Add space|添加空间/i;
  var CREATE_ROOM_SKIP_RE =
    /开始聊天|开始私聊|私信|Start chat|Start a chat|Direct message|Message|发送私信/i;

  /* 外观页内：主题选择、匹配系统主题（勿匹配整页「外观/Appearance」标题） */
  var THEME_SECTION_RE =
    /^(主题|Theme|匹配系统主题|Match system theme|跟随系统主题|Use system theme|自定义主题|Custom themes?)$/i;
  var THEME_MENU_RE =
    /^(主题|Theme|浅色|深色|Light|Dark|匹配系统主题|Match system theme)$/i;

  /* 账户设置：显示名称（Synapse enable_set_displayname=false；UI 再藏一层） */
  var DISPLAY_NAME_RE = /^(显示名称|Display Name|Display name)$/i;

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

  function hideDisplayNameUi() {
    var roots = document.querySelectorAll(
      ".mx_UserProfileSettings, .mx_AccountUserSettingsTab, .mx_SettingsTab, .mx_tabpanel"
    );
    for (var r = 0; r < roots.length; r++) {
      var root = roots[r];
      var labels = root.querySelectorAll(
        "label, .mx_Field_label, .mx_SettingsSubsection_heading, .mx_SettingsSubsectionHeading_heading, h2, h3, h4, [role='heading'], span, p, legend"
      );
      for (var i = 0; i < labels.length; i++) {
        var el = labels[i];
        var text = (el.textContent || "").replace(/\s+/g, " ").trim();
        if (!DISPLAY_NAME_RE.test(text)) continue;
        // 只藏 Field / Subsection，避免误藏整块头像区 profile_controls
        var wrap =
          el.closest(".mx_Field, .mx_SettingsSubsection, .mx_SettingsFlag") ||
          el.parentElement;
        if (wrap) {
          wrap.setAttribute("data-jingepi-hide-displayname", "1");
        }
      }
      var inputs = root.querySelectorAll(
        "input[placeholder*='显示名称'], input[placeholder*='Display name'], input[placeholder*='Display Name'], input[name='displayname'], input[name='displayName'], input[aria-label*='显示名称'], input[aria-label*='Display name'], input[aria-label*='Display Name'], textarea[aria-label*='显示名称'], textarea[aria-label*='Display name']"
      );
      for (var j = 0; j < inputs.length; j++) {
        var inp = inputs[j];
        var box =
          inp.closest(".mx_Field, .mx_SettingsSubsection") || inp.parentElement || inp;
        box.setAttribute("data-jingepi-hide-displayname", "1");
      }
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

  function matrixAccessToken() {
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i) || "";
        if (k.indexOf("mx_access_token") === 0 || k === "access_token") {
          var v = localStorage.getItem(k);
          if (v && v.length > 8) return v;
        }
      }
      var raw = localStorage.getItem("mx_local_settings");
      if (raw) {
        var s = JSON.parse(raw);
        if (s && typeof s.access_token === "string") return s.access_token;
      }
    } catch (_e) {
      /* ignore */
    }
    return null;
  }

  function applyCreateCapability(allowed) {
    canCreateRooms = !!allowed;
    try {
      if (canCreateRooms) {
        document.body.removeAttribute("data-jingepi-no-create");
      } else {
        document.body.setAttribute("data-jingepi-no-create", "1");
      }
    } catch (_e2) {
      /* ignore */
    }
  }

  function refreshCreateCapability() {
    var headers = { Accept: "application/json" };
    var tok = matrixAccessToken();
    if (tok) headers.Authorization = "Bearer " + tok;
    fetch("/api/matrix/capabilities", {
      method: "GET",
      credentials: "include",
      headers: headers,
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (!data || data.success === false) {
          applyCreateCapability(false);
          return;
        }
        applyCreateCapability(!!(data.can_create_room || data.can_create_space));
      })
      .catch(function () {
        /* 失败时不强制隐藏管理员入口；服务端仍会拦截 */
      });
  }

  function hideCreateRoomUi() {
    if (canCreateRooms !== false) return;
    try {
      document.body.setAttribute("data-jingepi-no-create", "1");
    } catch (_e) {
      /* ignore */
    }
    var nodes = document.querySelectorAll(
      "button, a, [role='button'], [role='menuitem'], [role='option'], .mx_AccessibleButton, .mx_MenuItem, li"
    );
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var text = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (!text || text.length > 64) continue;
      if (CREATE_ROOM_SKIP_RE.test(text)) continue;
      if (!CREATE_ROOM_RE.test(text)) continue;
      var wrap =
        el.closest(
          "[role='menuitem'], [role='option'], .mx_IconizedContextMenu_item, .mx_AccessibleButton, button, a, li"
        ) || el;
      wrap.setAttribute("data-jingepi-hide-create", "1");
    }
  }

  function suppress() {
    suppressToasts();
    hideEncryptionTabs();
    hideSectionsByHeading();
    hideRoomEncryptionToggles();
    hideAddServerUi();
    hideThemeSwitcher();
    hideDisplayNameUi();
    hideCreateRoomUi();
    forceGoldCssVars(document.documentElement);
    forceGoldCssVars(document.body);
    paintInlineGreens(document);
  }

  var obs = new MutationObserver(suppress);

  function start() {
    forceJinGeTheme();
    injectCss();
    refreshCreateCapability();
    setInterval(refreshCreateCapability, 30000);
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
