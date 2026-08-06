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
 * 11) 房间顶栏：视频/语音/消息列/房间信息收入「更多」面板（无官方 config）
 * 12) 房间顶栏隐藏成员 FacePile（圆形头像堆 + 人数）；保留「⋯」更多；
 *     房间信息从「⋯ → 房间信息」进入
 * 13) 左侧栏折叠分隔条（|| / SeparatorView bar）改为明确「展开/收起」按钮
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

    /* 金色主按钮：只给登录/对话框/SSO，勿染展开等图标按钮（会拉伸变形） */
    ".mx_Login_submit,",
    ".mx_Dialog_primary,",
    ".mx_Dialog button.mx_Dialog_primary,",
    ".mx_Dialog_buttons button.mx_Dialog_primary,",
    ".mx_SSOButton,",
    ".mx_SSOButton_default {",
    "  background-color: " + GOLD_BTN + " !important;",
    "  background: " + GOLD_BTN + " !important;",
    "  border-color: " + GOLD_BTN + " !important;",
    "  color: " + GOLD_ON + " !important;",
    "  --cpd-color-text-on-solid-primary: " + GOLD_ON + " !important;",
    "  --cpd-color-icon-on-solid-primary: " + GOLD_ON + " !important;",
    "  border-radius: 14px !important;",
    "}",

    ".mx_Login_submit:hover,",
    ".mx_Dialog_primary:hover,",
    ".mx_SSOButton:hover,",
    ".mx_SSOButton_default:hover {",
    "  background-color: " + GOLD_HOVER + " !important;",
    "  background: " + GOLD_HOVER + " !important;",
    "  border-color: " + GOLD_HOVER + " !important;",
    "  color: " + GOLD_ON + " !important;",
    "}",

    ".mx_Login_submit:active,",
    ".mx_Dialog_primary:active,",
    ".mx_SSOButton:active,",
    ".mx_SSOButton_default:active {",
    "  background-color: " + GOLD_PRESSED + " !important;",
    "  background: " + GOLD_PRESSED + " !important;",
    "  border-color: " + GOLD_PRESSED + " !important;",
    "  color: " + GOLD_ON + " !important;",
    "}",

    ".mx_Login_submit svg,",
    ".mx_Dialog_primary svg,",
    ".mx_SSOButton svg,",
    ".mx_Login_submit svg path,",
    ".mx_Dialog_primary svg path,",
    ".mx_SSOButton svg path {",
    "  color: " + GOLD_ON + " !important;",
    "  fill: currentColor !important;",
    "  stroke: currentColor;",
    "}",

    /* outline 金色描边只给文字 CTA，勿染含 SVG 的展开/顶栏图标 */
    ".mx_AccessibleButton_kind_primary_outline:not(:has(svg)),",
    ".mx_AccessibleButton_kind_primary_outline.mx_AccessibleButton:not(:has(svg)) {",
    "  color: " + GOLD + " !important;",
    "  border-color: " + GOLD + " !important;",
    "}",

    ".mx_AccessibleButton_kind_primary_outline:not(:has(svg)):hover {",
    "  color: " + GOLD_HOVER + " !important;",
    "  border-color: " + GOLD_HOVER + " !important;",
    "  background-color: rgba(240, 185, 11, 0.12) !important;",
    "}",

    /* 顶栏 / 房间列表头图标：交还 Element，避免竖长黄椭圆与头像拉伸 */
    ".mx_RoomHeader .cpd-button,",
    ".mx_RoomHeader .mx_AccessibleButton,",
    ".mx_RoomHeader button,",
    ".mx_RoomHeader_wrapper .cpd-button,",
    ".mx_RoomHeader_wrapper .mx_AccessibleButton,",
    ".mx_RoomHeader_wrapper button,",
    ".mx_LegacyRoomHeader .cpd-button,",
    ".mx_LegacyRoomHeader .mx_AccessibleButton,",
    ".mx_LegacyRoomHeader button,",
    ".mx_RoomListHeader .cpd-button,",
    ".mx_RoomListHeader .mx_AccessibleButton,",
    ".mx_RoomListHeader button,",
    ".mx_AccessibleButton_kind_primary:has(svg),",
    ".mx_AccessibleButton_kind_primary_outline:has(svg),",
    ".mx_AccessibleButton_kind_secondary:has(svg),",
    ".cpd-button[data-kind='primary']:has(svg),",
    ".cpd-button[data-kind='secondary']:has(svg),",
    ".cpd-button[data-kind='tertiary']:has(svg) {",
    "  width: revert-layer !important;",
    "  height: revert-layer !important;",
    "  min-width: revert-layer !important;",
    "  min-height: revert-layer !important;",
    "  max-width: none !important;",
    "  max-height: none !important;",
    "  padding: revert-layer !important;",
    "  aspect-ratio: auto !important;",
    "  border-radius: revert-layer !important;",
    "  transform: none !important;",
    "  background: revert-layer !important;",
    "  background-color: revert-layer !important;",
    "  border: revert-layer !important;",
    "  border-color: revert-layer !important;",
    "  color: revert-layer !important;",
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

    "/* ---- 房间顶栏：隐藏成员 FacePile（保留「⋯」更多） ---- */",
    ".mx_RoomHeader .mx_FacePile,",
    ".mx_RoomHeader .mx_RoomHeader_members,",
    ".mx_RoomHeader_wrapper .mx_FacePile,",
    ".mx_RoomHeader_wrapper .mx_RoomHeader_members,",
    ".mx_LegacyRoomHeader .mx_FacePile,",
    ".mx_LegacyRoomHeader .mx_RoomHeader_members,",
    ".mx_RoomHeader button[aria-label*='成员'],",
    ".mx_RoomHeader button[aria-label*='Members'],",
    ".mx_RoomHeader button[aria-label*='members'],",
    ".mx_RoomHeader [role='button'][aria-label*='成员'],",
    ".mx_RoomHeader [role='button'][aria-label*='Members'],",
    ".mx_RoomHeader [role='button'][aria-label*='members'],",
    ".mx_LegacyRoomHeader button[aria-label*='成员'],",
    ".mx_LegacyRoomHeader button[aria-label*='Members'],",
    ".mx_LegacyRoomHeader button[aria-label*='members'] {",
    "  display: none !important;",
    "}",

    "/* ---- 房间顶栏：把视频/语音/消息列/信息收进「更多」 ---- */",
    ".mx_RoomHeader [data-jingepi-header-overflow='1'],",
    ".mx_LegacyRoomHeader [data-jingepi-header-overflow='1'] {",
    "  display: none !important;",
    "}",
    "#jingepi-room-header-more {",
    "  position: relative;",
    "  display: inline-flex;",
    "  align-items: center;",
    "  flex-shrink: 0;",
    "  z-index: 6;",
    "}",
    "#jingepi-room-header-more > button.jingepi-room-header-more-btn {",
    "  display: inline-flex !important;",
    "  align-items: center;",
    "  justify-content: center;",
    "  width: 32px !important;",
    "  height: 32px !important;",
    "  min-width: 32px !important;",
    "  min-height: 32px !important;",
    "  padding: 0 !important;",
    "  margin: 0 !important;",
    "  border: none !important;",
    "  border-radius: 999px !important;",
    "  background: transparent !important;",
    "  color: " + TEXT + " !important;",
    "  cursor: pointer;",
    "  font-size: 18px;",
    "  line-height: 1;",
    "  letter-spacing: 0.02em;",
    "}",
    "#jingepi-room-header-more > button.jingepi-room-header-more-btn:hover,",
    "#jingepi-room-header-more > button.jingepi-room-header-more-btn[aria-expanded='true'] {",
    "  background: rgba(240, 185, 11, 0.12) !important;",
    "  color: " + GOLD + " !important;",
    "}",
    "#jingepi-room-header-more-panel {",
    "  display: none;",
    "  position: absolute;",
    "  top: calc(100% + 6px);",
    "  right: 0;",
    "  min-width: 168px;",
    "  padding: 6px;",
    "  flex-direction: column;",
    "  gap: 2px;",
    "  border-radius: 12px;",
    "  border: 1px solid " + BORDER + ";",
    "  background: " + PANEL_RAISED + ";",
    "  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.35);",
    "  z-index: 40;",
    "}",
    "#jingepi-room-header-more-panel[data-open='1'] {",
    "  display: flex;",
    "}",
    "#jingepi-room-header-more-panel button {",
    "  display: flex;",
    "  align-items: center;",
    "  width: 100%;",
    "  gap: 10px;",
    "  padding: 8px 10px;",
    "  border: none;",
    "  border-radius: 8px;",
    "  background: transparent;",
    "  color: " + TEXT + ";",
    "  font-size: 13px;",
    "  text-align: left;",
    "  cursor: pointer;",
    "  white-space: nowrap;",
    "}",
    "#jingepi-room-header-more-panel button:hover {",
    "  background: rgba(240, 185, 11, 0.12);",
    "  color: " + GOLD + ";",
    "}",
    "#jingepi-room-header-more-panel button[disabled] {",
    "  opacity: 0.45;",
    "  cursor: not-allowed;",
    "}",

    "/* ---- 左侧栏 || 分隔条 → 明确展开/收起按钮 ---- */",
    "[role='separator'][data-separator-type='bar'] {",
    "  width: 40px !important;",
    "  min-width: 40px !important;",
    "  opacity: 0 !important;",
    "  pointer-events: none !important;",
    "  border: none !important;",
    "  background: transparent !important;",
    "}",
    "[role='separator'][data-separator-type='bar'] svg {",
    "  display: none !important;",
    "}",
    "#jingepi-left-panel-toggle {",
    "  position: fixed;",
    "  z-index: 120;",
    "  display: inline-flex;",
    "  align-items: center;",
    "  justify-content: center;",
    "  box-sizing: border-box;",
    "  min-width: 36px;",
    "  min-height: 36px;",
    "  height: 36px;",
    "  padding: 0 12px;",
    "  margin: 0;",
    "  border: 1px solid rgba(240, 185, 11, 0.45);",
    "  border-radius: 10px;",
    "  background: " + SURFACE + ";",
    "  color: " + GOLD + ";",
    "  font-size: 13px;",
    "  font-weight: 600;",
    "  line-height: 1;",
    "  white-space: nowrap;",
    "  cursor: pointer;",
    "  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);",
    "  transform: translateY(-50%);",
    "}",
    "#jingepi-left-panel-toggle:hover {",
    "  background: rgba(240, 185, 11, 0.12);",
    "  border-color: " + GOLD + ";",
    "  color: " + GOLD_LIGHT + ";",
    "}",
    "#jingepi-left-panel-toggle[data-jingepi-panel-state='collapsed'] {",
    "  left: max(8px, env(safe-area-inset-left, 0px));",
    "  top: 50%;",
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

  /* 顶栏四键：视频 / 语音 / 消息列(线程) / 房间信息 → 「更多」；FacePile 由 CSS 隐藏 */
  var HEADER_ACTION_DEFS = [
    {
      key: "video",
      labelRe: /^(视频通话|Video call)$/i,
      title: "视频通话",
    },
    {
      key: "voice",
      labelRe: /^(语音通话|Voice call)$/i,
      title: "语音通话",
    },
    {
      key: "threads",
      labelRe: /^(消息列|Threads)$/i,
      title: "消息列",
    },
    {
      key: "info",
      labelRe: /^(房间信息|Room info)$/i,
      title: "房间信息",
    },
    {
      key: "join",
      labelRe: /^(加入视频通话|加入语音通话|Join video call|Join voice call)$/i,
      title: "加入通话",
    },
  ];

  var headerMoreOutsideBound = false;

  function headerBtnLabel(btn) {
    return (btn.getAttribute("aria-label") || btn.getAttribute("title") || "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function isHeaderExcludedBtn(btn) {
    if (!btn || btn.getAttribute("data-jingepi-header-more") === "1") return true;
    if (btn.closest("#jingepi-room-header-more")) return true;
    if (
      btn.closest(
        ".mx_RoomHeader_infoWrapper, .mx_RoomHeader_members, .mx_FacePile, .mx_RoomHeader_avatar"
      )
    ) {
      return true;
    }
    return false;
  }

  function classifyHeaderAction(btn) {
    var label = headerBtnLabel(btn);
    for (var i = 0; i < HEADER_ACTION_DEFS.length; i++) {
      if (HEADER_ACTION_DEFS[i].labelRe.test(label)) {
        return HEADER_ACTION_DEFS[i];
      }
    }
    return null;
  }

  function collectHeaderActionButtons(header) {
    var found = {};
    var candidates = [];
    var nodes = header.querySelectorAll("button, [role='button']");
    for (var i = 0; i < nodes.length; i++) {
      var btn = nodes[i];
      if (isHeaderExcludedBtn(btn)) continue;
      candidates.push(btn);
      var def = classifyHeaderAction(btn);
      if (def && !found[def.key]) found[def.key] = btn;
    }

    /* 禁用通话时 aria-label 会变成原因文案：按「消息列」前相邻图标按钮回退 */
    if ((!found.video || !found.voice) && found.threads) {
      var ti = candidates.indexOf(found.threads);
      var before = [];
      for (var j = 0; j < ti; j++) {
        var b = candidates[j];
        if (found.join === b || found.video === b || found.voice === b) continue;
        if (b.classList && b.classList.contains("mx_RoomHeader_join_button")) {
          continue;
        }
        if (!b.querySelector || !b.querySelector("svg")) continue;
        if (classifyHeaderAction(b)) continue;
        before.push(b);
      }
      var bi = 0;
      if (!found.video && before[bi]) found.video = before[bi++];
      if (!found.voice && before[bi]) found.voice = before[bi++];
    }
    return found;
  }

  function closeHeaderMorePanel() {
    var panel = document.getElementById("jingepi-room-header-more-panel");
    var btn = document.querySelector(
      "#jingepi-room-header-more > button.jingepi-room-header-more-btn"
    );
    if (panel) panel.removeAttribute("data-open");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function ensureHeaderMoreOutsideClose() {
    if (headerMoreOutsideBound) return;
    headerMoreOutsideBound = true;
    document.addEventListener(
      "pointerdown",
      function (ev) {
        var wrap = document.getElementById("jingepi-room-header-more");
        if (!wrap || !wrap.contains(ev.target)) closeHeaderMorePanel();
      },
      true
    );
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeHeaderMorePanel();
    });
  }

  function ensureHeaderMoreUi(header) {
    var wrap = document.getElementById("jingepi-room-header-more");
    if (wrap && !header.contains(wrap)) {
      wrap.remove();
      wrap = null;
    }
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.id = "jingepi-room-header-more";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "jingepi-room-header-more-btn";
      btn.setAttribute("data-jingepi-header-more", "1");
      btn.setAttribute("aria-label", "更多");
      btn.setAttribute("aria-haspopup", "menu");
      btn.setAttribute("aria-expanded", "false");
      btn.setAttribute("title", "更多");
      btn.textContent = "⋯";
      var panel = document.createElement("div");
      panel.id = "jingepi-room-header-more-panel";
      panel.setAttribute("role", "menu");
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var open = panel.getAttribute("data-open") === "1";
        if (open) {
          closeHeaderMorePanel();
        } else {
          panel.setAttribute("data-open", "1");
          btn.setAttribute("aria-expanded", "true");
        }
      });
      wrap.appendChild(btn);
      wrap.appendChild(panel);
    }

    var members = header.querySelector(".mx_RoomHeader_members");
    var insertBefore = null;
    if (members) {
      insertBefore = members;
      while (insertBefore.parentElement && insertBefore.parentElement !== header) {
        insertBefore = insertBefore.parentElement;
      }
    }
    if (wrap.parentElement !== header) {
      if (insertBefore && insertBefore.parentElement === header) {
        header.insertBefore(wrap, insertBefore);
      } else {
        header.appendChild(wrap);
      }
    } else if (
      insertBefore &&
      insertBefore.parentElement === header &&
      wrap.nextSibling !== insertBefore
    ) {
      header.insertBefore(wrap, insertBefore);
    }
    ensureHeaderMoreOutsideClose();
    return wrap;
  }

  function rebuildHeaderMorePanel(wrap, found) {
    var panel = wrap.querySelector("#jingepi-room-header-more-panel");
    if (!panel) return;
    var order = ["video", "voice", "threads", "info", "join"];
    var titles = {
      video: "视频通话",
      voice: "语音通话",
      threads: "消息列",
      info: "房间信息",
      join: "加入通话",
    };
    var sigParts = [];
    for (var i = 0; i < order.length; i++) {
      var key = order[i];
      var target = found[key];
      if (!target) continue;
      sigParts.push(
        key +
          ":" +
          (target.disabled || target.getAttribute("aria-disabled") === "true"
            ? "0"
            : "1") +
          ":" +
          headerBtnLabel(target)
      );
    }
    var sig = sigParts.join("|");
    if (panel.getAttribute("data-jingepi-sig") === sig) return;
    panel.setAttribute("data-jingepi-sig", sig);
    panel.textContent = "";

    for (var j = 0; j < order.length; j++) {
      var k = order[j];
      var src = found[k];
      if (!src) continue;
      var item = document.createElement("button");
      item.type = "button";
      item.setAttribute("role", "menuitem");
      var label = headerBtnLabel(src);
      var defTitle = titles[k];
      if (!label || !classifyHeaderAction(src)) label = defTitle;
      /* 禁用原因保留在菜单项上，便于理解为何不可点 */
      item.textContent = label || defTitle;
      var disabled =
        !!src.disabled || src.getAttribute("aria-disabled") === "true";
      if (disabled) item.disabled = true;
      (function (targetBtn) {
        item.addEventListener("click", function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          closeHeaderMorePanel();
          try {
            targetBtn.click();
          } catch (_e) {
            /* ignore */
          }
        });
      })(src);
      panel.appendChild(item);
    }

    wrap.style.display = panel.childNodes.length ? "" : "none";
  }

  /* ---- 左侧栏 SeparatorView（|| 细条）→ 展开/收起按钮 ---- */
  /*
   * Element ResizerViewModel 不用 DOM click 展开：
   * - 折叠(bar)：MouseClickHandler 在 pointerdown→pointerup（中间无 pointermove）时
   *   调用 onSeparatorClick → panelHandle.resize(...)
   * - 展开(border)：onDoubleClick → panelHandle.collapse()
   * （Separator 传了 disableDoubleClick，仅关掉库自带双击，Element 自有 onDoubleClick 仍生效）
   * 因此 s.click() / 拖拽模拟都会失效或很脆；必须派发上述官方事件序列。
   */
  function findLeftPanelSeparator() {
    return (
      document.querySelector("[role='separator'][data-separator-type]") ||
      document.querySelector(
        "[role='separator'][aria-label*='拖动'], [role='separator'][aria-label*='展开'], [role='separator'][aria-label*='expand'], [role='separator'][aria-label*='Expand']"
      )
    );
  }

  function leftPanelSeparatorPoint(sep) {
    var rect = sep.getBoundingClientRect();
    return {
      x: rect.left + Math.max(rect.width, 1) / 2,
      y: Math.min(
        Math.max(rect.top + rect.height / 2, 40),
        window.innerHeight - 40
      ),
    };
  }

  function fireLeftPanelPointer(target, type, x, y, buttons) {
    var opts = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: x,
      clientY: y,
      screenX: x,
      screenY: y,
      button: 0,
      buttons: buttons,
      pointerId: 1,
      pointerType: "mouse",
      isPrimary: true,
      pressure: buttons ? 0.5 : 0,
    };
    try {
      target.dispatchEvent(new PointerEvent(type, opts));
    } catch (_e) {
      target.dispatchEvent(
        new MouseEvent(type === "pointerdown" ? "mousedown" : "mouseup", opts)
      );
    }
  }

  /** 折叠态：pointerdown + pointerup（禁止 pointermove，否则被当成拖拽） */
  function expandLeftPanelViaSeparator(sep) {
    if (!sep) return;
    var pt = leftPanelSeparatorPoint(sep);
    /* bar 被 CSS 设为 pointer-events:none；临时放开以免个别路径走命中检测 */
    sep.style.setProperty("pointer-events", "auto", "important");
    try {
      fireLeftPanelPointer(sep, "pointerdown", pt.x, pt.y, 1);
      fireLeftPanelPointer(sep, "pointerup", pt.x, pt.y, 0);
    } finally {
      sep.style.removeProperty("pointer-events");
    }
  }

  /** 展开态：触发 SeparatorView onDoubleClick → panelHandle.collapse() */
  function collapseLeftPanelViaSeparator(sep) {
    if (!sep) return;
    var pt = leftPanelSeparatorPoint(sep);
    var opts = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: pt.x,
      clientY: pt.y,
      screenX: pt.x,
      screenY: pt.y,
      button: 0,
      buttons: 0,
      detail: 2,
    };
    try {
      sep.dispatchEvent(new MouseEvent("dblclick", opts));
    } catch (_e) {
      /* ignore */
    }
  }

  function enhanceLeftPanelToggle() {
    var sep = findLeftPanelSeparator();
    var btn = document.getElementById("jingepi-left-panel-toggle");
    if (!sep) {
      if (btn) btn.remove();
      return;
    }

    var type = sep.getAttribute("data-separator-type") || "";
    var collapsed = type === "bar";

    if (!btn) {
      btn = document.createElement("button");
      btn.id = "jingepi-left-panel-toggle";
      btn.type = "button";
      btn.className = "jingepi-left-panel-toggle";
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var s = findLeftPanelSeparator();
        if (!s) return;
        if (s.getAttribute("data-separator-type") === "bar") {
          expandLeftPanelViaSeparator(s);
        } else {
          collapseLeftPanelViaSeparator(s);
        }
      });
      (document.body || document.documentElement).appendChild(btn);
    }

    var label = collapsed ? "展开" : "收起";
    if (btn.textContent !== label) btn.textContent = label;
    btn.setAttribute("aria-label", collapsed ? "展开侧栏" : "收起侧栏");
    btn.setAttribute("title", label);
    btn.setAttribute(
      "data-jingepi-panel-state",
      collapsed ? "collapsed" : "expanded"
    );

    var rect = sep.getBoundingClientRect();
    if (collapsed) {
      btn.style.left = "";
      btn.style.top = "";
      btn.style.right = "";
    } else {
      var left = Math.max(8, Math.round(rect.left - 4));
      /* 贴在分隔条左侧，避免挡住聊天区 */
      if (left > 48) left = Math.round(rect.left - btn.offsetWidth - 8);
      btn.style.left = left + "px";
      btn.style.top = "50%";
      btn.style.right = "auto";
    }
  }

  function collapseRoomHeaderActions() {
    var headers = document.querySelectorAll(
      "header.mx_RoomHeader, .mx_RoomHeader, .mx_LegacyRoomHeader"
    );
    if (!headers.length) {
      var orphan = document.getElementById("jingepi-room-header-more");
      if (orphan) orphan.remove();
      return;
    }

    for (var h = 0; h < headers.length; h++) {
      var header = headers[h];
      var stale = header.querySelectorAll("[data-jingepi-header-overflow='1']");
      for (var s = 0; s < stale.length; s++) {
        stale[s].removeAttribute("data-jingepi-header-overflow");
      }

      var found = collectHeaderActionButtons(header);
      var keys = Object.keys(found);
      if (!keys.length) {
        var empty = header.querySelector("#jingepi-room-header-more");
        if (empty) empty.style.display = "none";
        continue;
      }

      for (var i = 0; i < keys.length; i++) {
        var btn = found[keys[i]];
        btn.setAttribute("data-jingepi-header-overflow", "1");
        /* Tooltip / Menu 壳若只包这一颗按钮，一并藏掉以免留空位 */
        var parent = btn.parentElement;
        if (
          parent &&
          parent !== header &&
          !parent.classList.contains("mx_RoomHeader") &&
          parent.children.length === 1 &&
          !parent.querySelector(".mx_RoomHeader_members, .mx_FacePile")
        ) {
          parent.setAttribute("data-jingepi-header-overflow", "1");
        }
      }

      var wrap = ensureHeaderMoreUi(header);
      rebuildHeaderMorePanel(wrap, found);
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
    collapseRoomHeaderActions();
    enhanceLeftPanelToggle();
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
