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
 * 8) 强制强调色 / CTA 为金格金（覆盖 Element / Compound 默认绿；主按钮为金色玻璃，非纯实心）
 * 9) 确保 lab-jingepi-theme.css 已加载（nginx 注入兜底；玻璃材质/字体以该 CSS 为主）
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
 * 14) 窄屏消息输入四段：[更多] [输入完整「发送消息…」] [语音] [表情]；
 *     复用 Element composer ⋯ 菜单收纳附件等；桌面布局不动
 * 15) 设置 Dialog 居中最大化（非贴边真全屏）：Element 1.12+ 结构为
 *     Dialog_wrapper > Dialog_border > Dialog > UserSettingsDialog；
 *     CSS :has 可能被更高优先级盖住时，打 data-jingepi-fullscreen-settings + 内联最大化样式
 * 16) 窄屏（≤900px）QQ 式信息架构：频道列表全屏页 ↔ 聊天全屏页；
 *     聊天顶栏居中标题 + 左返回（回列表，非 history.back）；
 *     列表页顶部 Tab（频道 | 空间 | 我的）；「空间」打开 Space 列表选空间；
 *     设置经「我的」进个人菜单；隐藏左侧可拖分割条与「展开所有」浮钮；
 *     聊天页藏 Tab/Space；桌面分栏不动
 * 17) 允许手机 Web：写入 element_mobile_redirect_to_guide=false，避免被
 *     Element 内置 /mobile_guide/（「desktop site does not work on mobile」）挡住；
 *     并顺带隐藏 mobile_guide Toast（config 已关 mobile_guide_toast 作双保险）
 */
(function () {
  try {
    document.cookie =
      "element_mobile_redirect_to_guide=false;path=/;max-age=31536000";
  } catch (_cookieErr) {
    /* ignore */
  }

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

    "/* ---- 金格色板 + 玻璃 token（与 lab-jingepi-theme.css 双保险；勿用纯实心金覆盖玻璃） ---- */",
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

    /* 金色玻璃主按钮：登录/对话框/SSO；勿染展开等图标按钮 */
    ".mx_Login_submit,",
    ".mx_Dialog_primary,",
    ".mx_Dialog button.mx_Dialog_primary,",
    ".mx_Dialog_buttons button.mx_Dialog_primary,",
    ".mx_SSOButton,",
    ".mx_SSOButton_default {",
    "  background: linear-gradient(160deg, rgba(252,213,53,.88) 0%, rgba(240,185,11,.82) 45%, rgba(201,148,0,.78) 100%) !important;",
    "  border: 1px solid rgba(255,255,255,.28) !important;",
    "  color: " + GOLD_ON + " !important;",
    "  --cpd-color-text-on-solid-primary: " + GOLD_ON + " !important;",
    "  --cpd-color-icon-on-solid-primary: " + GOLD_ON + " !important;",
    "  border-radius: 14px !important;",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.38), inset 0 -1px 0 rgba(0,0,0,.22), 0 0 18px rgba(240,185,11,.28) !important;",
    "  backdrop-filter: blur(8px) saturate(140%) brightness(1.05);",
    "  -webkit-backdrop-filter: blur(8px) saturate(140%) brightness(1.05);",
    "  font-weight: 600 !important;",
    "}",

    ".mx_Login_submit:hover,",
    ".mx_Dialog_primary:hover,",
    ".mx_SSOButton:hover,",
    ".mx_SSOButton_default:hover {",
    "  background: linear-gradient(160deg, rgba(252,213,53,.95) 0%, rgba(240,185,11,.9) 45%, rgba(201,148,0,.85) 100%) !important;",
    "  border-color: rgba(255,255,255,.38) !important;",
    "  color: " + GOLD_ON + " !important;",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.48), 0 0 22px rgba(240,185,11,.42), 0 8px 20px rgba(0,0,0,.28) !important;",
    "}",

    ".mx_Login_submit:active,",
    ".mx_Dialog_primary:active,",
    ".mx_SSOButton:active,",
    ".mx_SSOButton_default:active {",
    "  background: linear-gradient(160deg, rgba(224,168,10,.9) 0%, rgba(201,148,0,.88) 100%) !important;",
    "  border-color: rgba(255,255,255,.22) !important;",
    "  color: " + GOLD_ON + " !important;",
    "  box-shadow: inset 0 2px 6px rgba(0,0,0,.25), inset 0 1px 0 rgba(255,255,255,.2) !important;",
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

    /* outline：暗玻璃 + 金边（文字 CTA） */
    ".mx_AccessibleButton_kind_primary_outline:not(:has(svg)),",
    ".mx_AccessibleButton_kind_primary_outline.mx_AccessibleButton:not(:has(svg)) {",
    "  color: " + GOLD + " !important;",
    "  border: 1px solid rgba(240,185,11,.42) !important;",
    "  background: linear-gradient(155deg, rgba(255,255,255,.1) 0%, rgba(80,80,86,.08) 38%, rgba(0,0,0,.16) 100%), rgba(36,36,40,.38) !important;",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.28), inset 0 -1px 0 rgba(0,0,0,.25) !important;",
    "  backdrop-filter: blur(14px) saturate(150%);",
    "  -webkit-backdrop-filter: blur(14px) saturate(150%);",
    "  border-radius: 14px !important;",
    "}",

    ".mx_AccessibleButton_kind_primary_outline:not(:has(svg)):hover {",
    "  color: " + GOLD_LIGHT + " !important;",
    "  border-color: " + GOLD + " !important;",
    "  background: linear-gradient(155deg, rgba(255,255,255,.14) 0%, rgba(90,90,96,.12) 38%, rgba(0,0,0,.18) 100%), rgba(44,44,48,.48) !important;",
    "}",

    /* Spotlight「复制邀请链接」：外层 option 透明，内层一颗金色胶囊（禁大黄条套小按钮） */
    ".mx_SpotlightDialog_inviteLink.mx_SpotlightDialog_option,",
    ".mx_SpotlightDialog_createRoom.mx_SpotlightDialog_option,",
    ".mx_SpotlightDialog_inviteLink.mx_AccessibleButton,",
    ".mx_SpotlightDialog_createRoom.mx_AccessibleButton {",
    "  background: transparent !important;",
    "  border: none !important;",
    "  box-shadow: none !important;",
    "  backdrop-filter: none !important;",
    "  -webkit-backdrop-filter: none !important;",
    "  width: auto !important;",
    "  max-width: 100% !important;",
    "  min-height: 0 !important;",
    "  padding: 6px 4px !important;",
    "  filter: none !important;",
    "}",
    ".mx_SpotlightDialog_inviteLink.mx_SpotlightDialog_option:hover,",
    ".mx_SpotlightDialog_createRoom.mx_SpotlightDialog_option:hover,",
    ".mx_SpotlightDialog_inviteLink.mx_SpotlightDialog_option[aria-selected='true'],",
    ".mx_SpotlightDialog_createRoom.mx_SpotlightDialog_option[aria-selected='true'] {",
    "  background: transparent !important;",
    "  box-shadow: none !important;",
    "}",
    ".mx_SpotlightDialog_inviteLink .mx_AccessibleButton_kind_primary_outline,",
    ".mx_SpotlightDialog_createRoom .mx_AccessibleButton_kind_primary_outline {",
    "  display: inline-flex !important;",
    "  align-items: center !important;",
    "  width: auto !important;",
    "  max-width: 100% !important;",
    "  min-height: 40px !important;",
    "  margin: 0 !important;",
    "  padding: 0 18px 0 36px !important;",
    "  border-radius: 999px !important;",
    "  background: linear-gradient(160deg, rgba(252,213,53,.88) 0%, rgba(240,185,11,.82) 45%, rgba(201,148,0,.78) 100%) !important;",
    "  border: 1px solid rgba(255,255,255,.28) !important;",
    "  color: " + GOLD_ON + " !important;",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.38), inset 0 -1px 0 rgba(0,0,0,.22), 0 0 18px rgba(240,185,11,.28) !important;",
    "  backdrop-filter: blur(8px) saturate(140%) brightness(1.05);",
    "  -webkit-backdrop-filter: blur(8px) saturate(140%) brightness(1.05);",
    "  font-weight: 600 !important;",
    "}",
    ".mx_SpotlightDialog_inviteLink .mx_AccessibleButton_kind_primary_outline svg,",
    ".mx_SpotlightDialog_createRoom .mx_AccessibleButton_kind_primary_outline svg {",
    "  color: " + GOLD_ON + " !important;",
    "  fill: currentColor !important;",
    "  left: 12px !important;",
    "}",

    /* 顶栏 / 列表头纯图标：圆形玻璃；勿用 50% 染「邀请」等宽文字 CTA（会变成扁透镜） */
    ".mx_RoomHeader .cpd-button:has(svg),",
    ".mx_RoomHeader .mx_AccessibleButton:has(svg),",
    ".mx_RoomHeader_wrapper .cpd-button:has(svg),",
    ".mx_RoomHeader_wrapper .mx_AccessibleButton:has(svg),",
    ".mx_LegacyRoomHeader .cpd-button:has(svg),",
    ".mx_LegacyRoomHeader .mx_AccessibleButton:has(svg),",
    ".mx_RoomListHeader .cpd-button:has(svg),",
    ".mx_RoomListHeader .mx_AccessibleButton:has(svg) {",
    "  width: revert-layer !important;",
    "  height: revert-layer !important;",
    "  min-width: revert-layer !important;",
    "  min-height: revert-layer !important;",
    "  max-width: none !important;",
    "  max-height: none !important;",
    "  padding: revert-layer !important;",
    "  aspect-ratio: auto !important;",
    "  transform: none !important;",
    "  border-radius: 50% !important;",
    "  background: linear-gradient(155deg, rgba(255,255,255,.1) 0%, rgba(80,80,86,.08) 38%, rgba(0,0,0,.16) 100%), rgba(36,36,40,.38) !important;",
    "  border: 1px solid rgba(255,255,255,.14) !important;",
    "  color: " + TEXT + " !important;",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.28), inset 0 -1px 0 rgba(0,0,0,.25) !important;",
    "  backdrop-filter: blur(14px) saturate(150%);",
    "  -webkit-backdrop-filter: blur(14px) saturate(150%);",
    "}",
    /* 邀请等到此房间：胶囊 pill */
    ".mx_RoomPreviewBar .mx_AccessibleButton,",
    ".mx_EmptyRoom .mx_AccessibleButton,",
    ".mx_EmptyState .mx_AccessibleButton,",
    "button[aria-label*='邀请到此房间'],",
    "button[aria-label*='Invite to this room'],",
    ".mx_AccessibleButton[aria-label*='邀请到此房间'],",
    ".mx_AccessibleButton[aria-label*='Invite to this room'] {",
    "  width: auto !important;",
    "  height: auto !important;",
    "  min-height: 40px !important;",
    "  padding: 0 20px !important;",
    "  aspect-ratio: auto !important;",
    "  display: inline-flex !important;",
    "  align-items: center !important;",
    "  justify-content: center !important;",
    "  border-radius: 999px !important;",
    "  background: linear-gradient(155deg, rgba(255,255,255,.1) 0%, rgba(80,80,86,.08) 38%, rgba(0,0,0,.16) 100%), rgba(36,36,40,.38) !important;",
    "  border: 1px solid rgba(240,185,11,.42) !important;",
    "  color: " + GOLD + " !important;",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.28), inset 0 -1px 0 rgba(0,0,0,.25), 0 0 14px rgba(240,185,11,.12) !important;",
    "  backdrop-filter: blur(14px) saturate(150%);",
    "  -webkit-backdrop-filter: blur(14px) saturate(150%);",
    "  font-weight: 600 !important;",
    "}",
    ".mx_RoomHeader .mx_BaseAvatar,",
    ".mx_RoomHeader button:has(.mx_BaseAvatar),",
    ".mx_RoomHeader_wrapper button:has(.mx_BaseAvatar),",
    ".mx_LegacyRoomHeader button:has(.mx_BaseAvatar) {",
    "  background: transparent !important;",
    "  border: none !important;",
    "  box-shadow: none !important;",
    "  backdrop-filter: none !important;",
    "  -webkit-backdrop-filter: none !important;",
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
    "/* 勿用 display:none：React/程序化 click 常失效；改视觉隐藏仍可 .click() */",
    ".mx_RoomHeader [data-jingepi-header-overflow='1'],",
    ".mx_LegacyRoomHeader [data-jingepi-header-overflow='1'] {",
    "  position: absolute !important;",
    "  width: 1px !important;",
    "  height: 1px !important;",
    "  min-width: 0 !important;",
    "  min-height: 0 !important;",
    "  margin: 0 !important;",
    "  padding: 0 !important;",
    "  overflow: hidden !important;",
    "  clip: rect(0, 0, 0, 0) !important;",
    "  clip-path: inset(50%) !important;",
    "  border: 0 !important;",
    "  opacity: 0 !important;",
    "  pointer-events: none !important;",
    "  white-space: nowrap !important;",
    "}",
    "#jingepi-room-header-more {",
    "  position: relative;",
    "  display: inline-flex;",
    "  align-items: center;",
    "  flex-shrink: 0;",
    "  z-index: 500;",
    "  overflow: visible;",
    "  pointer-events: auto;",
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
    "  border: 1px solid rgba(255,255,255,.14) !important;",
    "  border-radius: 50% !important;",
    "  background: linear-gradient(155deg, rgba(255,255,255,.1) 0%, rgba(80,80,86,.08) 38%, rgba(0,0,0,.16) 100%), rgba(36,36,40,.38) !important;",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.28), inset 0 -1px 0 rgba(0,0,0,.25) !important;",
    "  backdrop-filter: blur(14px) saturate(150%);",
    "  -webkit-backdrop-filter: blur(14px) saturate(150%);",
    "  color: " + TEXT + " !important;",
    "  cursor: pointer;",
    "  pointer-events: auto;",
    "  font-size: 18px;",
    "  line-height: 1;",
    "  letter-spacing: 0.02em;",
    "}",
    "#jingepi-room-header-more > button.jingepi-room-header-more-btn:hover,",
    "#jingepi-room-header-more > button.jingepi-room-header-more-btn[aria-expanded='true'] {",
    "  background: linear-gradient(155deg, rgba(255,255,255,.14) 0%, rgba(90,90,96,.12) 38%, rgba(0,0,0,.18) 100%), rgba(44,44,48,.48) !important;",
    "  border-color: rgba(240,185,11,.35) !important;",
    "  color: " + GOLD + " !important;",
    "}",
    "/* 菜单挂到 body + fixed，避免被 RoomView/composer 盖住点不中 */",
    "#jingepi-room-header-more-panel {",
    "  display: none;",
    "  position: fixed;",
    "  top: 0;",
    "  left: 0;",
    "  min-width: 168px;",
    "  padding: 6px;",
    "  flex-direction: column;",
    "  gap: 2px;",
    "  border-radius: 14px;",
    "  border: 1px solid rgba(255,255,255,.14);",
    "  background: linear-gradient(155deg, rgba(255,255,255,.1) 0%, rgba(80,80,86,.08) 38%, rgba(0,0,0,.16) 100%), rgba(36,36,40,.92);",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.28), inset 0 -1px 0 rgba(0,0,0,.25), 0 12px 32px rgba(0,0,0,.45);",
    "  backdrop-filter: blur(22px) saturate(160%);",
    "  -webkit-backdrop-filter: blur(22px) saturate(160%);",
    "  z-index: 2147483000;",
    "  pointer-events: auto;",
    "  overflow: visible;",
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
    "  border: 1px solid transparent;",
    "  border-radius: 10px;",
    "  background: transparent;",
    "  color: " + TEXT + ";",
    "  font-size: 13px;",
    "  text-align: left;",
    "  cursor: pointer;",
    "  pointer-events: auto;",
    "  white-space: nowrap;",
    "  position: relative;",
    "  z-index: 1;",
    "}",
    "#jingepi-room-header-more-panel button:hover {",
    "  background: linear-gradient(155deg, rgba(240,185,11,.14) 0%, rgba(80,80,86,.1) 40%, rgba(0,0,0,.2) 100%), rgba(36,28,12,.45);",
    "  border-color: rgba(240,185,11,.28);",
    "  color: " + GOLD + ";",
    "}",
    "#jingepi-room-header-more-panel button[disabled] {",
    "  opacity: 0.45;",
    "  cursor: not-allowed;",
    "}",
    ".mx_RoomHeader,",
    ".mx_RoomHeader_wrapper,",
    ".mx_LegacyRoomHeader {",
    "  overflow: visible !important;",
    "  position: relative;",
    "  z-index: 40;",
    "}",

    "/* ---- 消息输入：只清外壳，勿清表情/附件/更多等操作钮 ---- */",
    ".mx_MessageComposer,",
    ".mx_MessageComposer_wrapper,",
    ".mx_SendMessageComposer,",
    ".mx_BasicMessageComposer,",
    ".mx_MessageComposer_row,",
    ".mx_MessageComposer_actions,",
    ".mx_MessageComposer_input_wrapper,",
    ".mx_SendWysiwygComposer,",
    ".mx_WysiwygComposer_Editor,",
    ".mx_WysiwygComposer_Editor_container {",
    "  background: transparent !important;",
    "  background-color: transparent !important;",
    "  border: none !important;",
    "  border-radius: 0 !important;",
    "  box-shadow: none !important;",
    "  outline: none !important;",
    "  backdrop-filter: none !important;",
    "  -webkit-backdrop-filter: none !important;",
    "}",
    ".mx_MessageComposer,",
    ".mx_MessageComposer_wrapper {",
    "  border-top: 1px solid rgba(255,255,255,.08) !important;",
    "  padding: 8px 10px !important;",
    "}",
    ".mx_MessageComposer_row {",
    "  display: flex !important;",
    "  flex-direction: row !important;",
    "  flex-wrap: nowrap !important;",
    "  align-items: center !important;",
    "  gap: 6px !important;",
    "  width: 100% !important;",
    "  min-width: 0 !important;",
    "  box-sizing: border-box !important;",
    "}",
    ".mx_MessageComposer .mx_SendWysiwygComposer,",
    ".mx_MessageComposer .mx_SendMessageComposer,",
    ".mx_MessageComposer .mx_BasicMessageComposer {",
    "  flex: 1 1 auto !important;",
    "  min-width: 0 !important;",
    "  width: auto !important;",
    "}",
    ".mx_MessageComposer_actions {",
    "  display: inline-flex !important;",
    "  flex: 0 0 auto !important;",
    "  align-items: center !important;",
    "  gap: 4px !important;",
    "}",
    "/* 输入栏旁操作钮：统一圆形玻璃；JS 打 data-jingepi-composer-icon */",
    "html body .mx_MessageComposer [data-jingepi-composer-icon='1'],",
    "html body .mx_MessageComposer .mx_MessageComposer_actions > button,",
    "html body .mx_MessageComposer .mx_MessageComposer_actions > [role='button'],",
    "html body .mx_MessageComposer .mx_MessageComposer_actions > .mx_AccessibleButton,",
    "html body .mx_MessageComposer .mx_MessageComposer_emoji,",
    "html body .mx_MessageComposer .mx_MessageComposer_stickers,",
    "html body .mx_MessageComposer .mx_MessageComposer_upload,",
    "html body .mx_MessageComposer .mx_MessageComposer_buttonMenu,",
    "html body .mx_MessageComposer .mx_MessageComposer_voiceMessage,",
    "html body .mx_MessageComposer .mx_MessageComposer_poll,",
    "html body .mx_MessageComposer .mx_MessageComposer_location,",
    "html body .mx_MessageComposer .mx_MessageComposer_sendMessage,",
    "html body .mx_MessageComposer .mx_MessageComposer_button:not(.mx_VoiceRecordComposerTile_delete):not(.mx_VoiceRecordComposerTile_stop):not([data-jingepi-composer-keep='voice-ctrl']),",
    "html body #jingepi-composer-more > button,",
    "html body #jingepi-composer-voice {",
    "  width: 36px !important;",
    "  height: 36px !important;",
    "  min-width: 36px !important;",
    "  min-height: 36px !important;",
    "  max-width: 36px !important;",
    "  max-height: 36px !important;",
    "  padding: 0 !important;",
    "  box-sizing: border-box !important;",
    "  display: inline-flex !important;",
    "  align-items: center !important;",
    "  justify-content: center !important;",
    "  flex: 0 0 36px !important;",
    "  border-radius: 50% !important;",
    "  background: linear-gradient(155deg, rgba(255,255,255,.1) 0%, rgba(80,80,86,.08) 38%, rgba(0,0,0,.16) 100%), rgba(36,36,40,.38) !important;",
    "  background-color: rgba(36,36,40,.38) !important;",
    "  border: 1px solid rgba(255,255,255,.14) !important;",
    "  color: " + TEXT_MUTED + " !important;",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.32), inset 0 -1px 0 rgba(0,0,0,.28) !important;",
    "  backdrop-filter: blur(14px) saturate(150%) !important;",
    "  -webkit-backdrop-filter: blur(14px) saturate(150%) !important;",
    "  font-size: 18px !important;",
    "  line-height: 1 !important;",
    "  cursor: pointer !important;",
    "}",
    "html body .mx_MessageComposer [data-jingepi-composer-icon='1']:hover,",
    "html body .mx_MessageComposer .mx_MessageComposer_emoji:hover,",
    "html body .mx_MessageComposer .mx_MessageComposer_upload:hover,",
    "html body .mx_MessageComposer .mx_MessageComposer_buttonMenu:hover,",
    "html body .mx_MessageComposer .mx_MessageComposer_voiceMessage:hover,",
    "html body .mx_MessageComposer .mx_MessageComposer_stickers:hover,",
    "html body .mx_MessageComposer .mx_MessageComposer_sendMessage:hover,",
    "html body #jingepi-composer-more > button:hover,",
    "html body #jingepi-composer-voice:hover {",
    "  color: " + GOLD + " !important;",
    "  border-color: rgba(240,185,11,.4) !important;",
    "  background: linear-gradient(155deg, rgba(255,255,255,.14) 0%, rgba(90,90,96,.12) 38%, rgba(0,0,0,.18) 100%), rgba(44,44,48,.48) !important;",
    "}",
    "html body .mx_MessageComposer [data-jingepi-composer-icon='1'] svg,",
    "html body .mx_MessageComposer .mx_MessageComposer_emoji svg,",
    "html body .mx_MessageComposer .mx_MessageComposer_upload svg,",
    "html body .mx_MessageComposer .mx_MessageComposer_buttonMenu svg,",
    "html body .mx_MessageComposer .mx_MessageComposer_voiceMessage svg,",
    "html body .mx_MessageComposer .mx_MessageComposer_stickers svg,",
    "html body .mx_MessageComposer .mx_MessageComposer_sendMessage svg,",
    "html body .mx_MessageComposer .mx_MessageComposer_actions > .mx_AccessibleButton svg,",
    "html body #jingepi-composer-more > button svg,",
    "html body #jingepi-composer-voice svg {",
    "  width: 20px !important;",
    "  height: 20px !important;",
    "  color: inherit !important;",
    "  fill: currentColor !important;",
    "}",
    ".mx_MessageComposer .mx_VoiceRecordComposerTile_delete {",
    "  width: 24px !important;",
    "  height: 24px !important;",
    "  min-width: 24px !important;",
    "  min-height: 24px !important;",
    "  border-radius: 0 !important;",
    "  background: transparent !important;",
    "  border: none !important;",
    "  box-shadow: none !important;",
    "  backdrop-filter: none !important;",
    "  -webkit-backdrop-filter: none !important;",
    "}",
    ".mx_MessageComposer .mx_VoiceRecordComposerTile_stop {",
    "  width: 20px !important;",
    "  height: 20px !important;",
    "  min-width: 20px !important;",
    "  min-height: 20px !important;",
    "  background: transparent !important;",
    "  border: 2px solid rgba(255,255,255,.35) !important;",
    "  border-radius: 32px !important;",
    "  box-shadow: none !important;",
    "  backdrop-filter: none !important;",
    "  -webkit-backdrop-filter: none !important;",
    "}",
    ".mx_MessageComposer .mx_BasicMessageComposer_input,",
    ".mx_BasicMessageComposer_input,",
    ".mx_MessageComposer textarea,",
    ".mx_MessageComposer [contenteditable='true'],",
    ".mx_MessageComposer [role='textbox'],",
    ".mx_WysiwygComposer_Editor_content,",
    ".mx_SendWysiwygComposer [contenteditable='true'] {",
    "  background: linear-gradient(155deg, rgba(255,255,255,.1) 0%, rgba(80,80,86,.08) 38%, rgba(0,0,0,.16) 100%), rgba(36,36,40,.38) !important;",
    "  border: 1px solid rgba(255,255,255,.14) !important;",
    "  border-radius: 999px !important;",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.28), inset 0 -1px 0 rgba(0,0,0,.25) !important;",
    "  outline: none !important;",
    "  backdrop-filter: blur(14px) saturate(150%);",
    "  -webkit-backdrop-filter: blur(14px) saturate(150%);",
    "  min-height: 40px !important;",
    "  height: auto !important;",
    "  width: 100% !important;",
    "  max-width: 100% !important;",
    "  min-width: 0 !important;",
    "  box-sizing: border-box !important;",
    "  color: " + TEXT + " !important;",
    "  display: flex !important;",
    "  align-items: center !important;",
    "  padding: 0 16px !important;",
    "  line-height: 1.35 !important;",
    "}",
    ".mx_MessageComposer textarea {",
    "  display: block !important;",
    "  padding: 10px 16px !important;",
    "  line-height: 20px !important;",
    "  resize: none !important;",
    "}",
    "@media screen and (max-width: 900px) {",
    "  .mx_MessageComposer, .mx_MessageComposer_wrapper {",
    "    flex: 0 0 auto !important;",
    "    width: 100% !important;",
    "    max-width: 100% !important;",
    "    overflow: visible !important;",
    "    transform: none !important;",
    "  }",
    "  .mx_MessageComposer_row {",
    "    display: flex !important;",
    "    flex-direction: row !important;",
    "    flex-wrap: nowrap !important;",
    "    align-items: center !important;",
    "    gap: 4px !important;",
    "    position: relative !important;",
    "  }",
    "  .mx_MessageComposer_row > #jingepi-composer-more {",
    "    order: 1 !important;",
    "    flex: 0 0 36px !important;",
    "  }",
    "  .mx_MessageComposer .mx_SendWysiwygComposer,",
    "  .mx_MessageComposer .mx_SendMessageComposer,",
    "  .mx_MessageComposer .mx_BasicMessageComposer {",
    "    order: 2 !important;",
    "    flex: 1 1 0% !important;",
    "    min-width: 8.5em !important;",
    "    max-width: none !important;",
    "    width: auto !important;",
    "  }",
    "  .mx_MessageComposer_actions {",
    "    order: 3 !important;",
    "    display: inline-flex !important;",
    "    flex: 0 0 auto !important;",
    "    flex-shrink: 0 !important;",
    "    min-width: 0 !important;",
    "    gap: 2px !important;",
    "  }",
    "  .mx_MessageComposer [data-jingepi-composer-overflow='1'],",
    "  .mx_MessageComposer_actions > .mx_MessageComposer_buttonMenu,",
    "  .mx_MessageComposer_actions > .mx_MessageComposer_upload,",
    "  .mx_MessageComposer_actions > .mx_MessageComposer_poll,",
    "  .mx_MessageComposer_actions > .mx_MessageComposer_location,",
    "  .mx_MessageComposer_actions > .mx_MessageComposer_plain_text,",
    "  .mx_MessageComposer_actions > .mx_MessageComposer_rich_text {",
    "    position: absolute !important;",
    "    width: 1px !important;",
    "    height: 1px !important;",
    "    min-width: 0 !important;",
    "    min-height: 0 !important;",
    "    margin: 0 !important;",
    "    padding: 0 !important;",
    "    overflow: hidden !important;",
    "    clip: rect(0, 0, 0, 0) !important;",
    "    clip-path: inset(50%) !important;",
    "    border: 0 !important;",
    "    opacity: 0 !important;",
    "    pointer-events: none !important;",
    "  }",
    "  .mx_MessageComposer_emoji,",
    "  .mx_MessageComposer_stickers,",
    "  .mx_MessageComposer_voiceMessage,",
    "  #jingepi-composer-voice,",
    "  #jingepi-composer-more > button {",
    "    display: inline-flex !important;",
    "    visibility: visible !important;",
    "    opacity: 1 !important;",
    "    flex: 0 0 36px !important;",
    "    width: 36px !important;",
    "    height: 36px !important;",
    "    min-width: 36px !important;",
    "    min-height: 36px !important;",
    "    position: relative !important;",
    "    pointer-events: auto !important;",
    "  }",
    "  .mx_MessageComposer_row > .mx_MessageComposer_sendMessage {",
    "    order: 2 !important;",
    "    position: absolute !important;",
    "    right: calc(76px + 4px) !important;",
    "    top: 50% !important;",
    "    transform: translateY(-50%) !important;",
    "    z-index: 5 !important;",
    "    width: 32px !important;",
    "    height: 32px !important;",
    "    border-radius: 50% !important;",
    "  }",
    "  /* 录音态：完整 VoiceRecord，取消(删除)钮可见 */",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_delete) #jingepi-composer-more,",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_stop) #jingepi-composer-more,",
    "  .mx_MessageComposer:has(.mx_VoiceMessagePrimaryContainer) #jingepi-composer-more,",
    "  .mx_MessageComposer[data-jingepi-recording='1'] #jingepi-composer-more,",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_delete) #jingepi-composer-voice,",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_stop) #jingepi-composer-voice,",
    "  .mx_MessageComposer:has(.mx_VoiceMessagePrimaryContainer) #jingepi-composer-voice,",
    "  .mx_MessageComposer[data-jingepi-recording='1'] #jingepi-composer-voice,",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_delete) .mx_MessageComposer_emoji,",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_stop) .mx_MessageComposer_emoji,",
    "  .mx_MessageComposer:has(.mx_VoiceMessagePrimaryContainer) .mx_MessageComposer_emoji,",
    "  .mx_MessageComposer[data-jingepi-recording='1'] .mx_MessageComposer_emoji,",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_delete) .mx_MessageComposer_stickers,",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_stop) .mx_MessageComposer_stickers,",
    "  .mx_MessageComposer:has(.mx_VoiceMessagePrimaryContainer) .mx_MessageComposer_stickers,",
    "  .mx_MessageComposer[data-jingepi-recording='1'] .mx_MessageComposer_stickers {",
    "    display: none !important;",
    "  }",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_delete) .mx_MessageComposer_actions,",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_stop) .mx_MessageComposer_actions,",
    "  .mx_MessageComposer:has(.mx_VoiceMessagePrimaryContainer) .mx_MessageComposer_actions,",
    "  .mx_MessageComposer[data-jingepi-recording='1'] .mx_MessageComposer_actions {",
    "    flex: 1 1 auto !important;",
    "    min-width: 0 !important;",
    "    overflow: visible !important;",
    "  }",
    "  .mx_MessageComposer .mx_VoiceRecordComposerTile_delete,",
    "  .mx_MessageComposer .mx_VoiceRecordComposerTile_stop,",
    "  .mx_MessageComposer .mx_VoiceMessagePrimaryContainer,",
    "  .mx_MessageComposer [data-jingepi-composer-keep='voice-ctrl'] {",
    "    display: inline-flex !important;",
    "    visibility: visible !important;",
    "    opacity: 1 !important;",
    "    pointer-events: auto !important;",
    "    position: relative !important;",
    "    clip: auto !important;",
    "    clip-path: none !important;",
    "    overflow: visible !important;",
    "  }",
    "  .mx_MessageComposer .mx_VoiceRecordComposerTile_delete {",
    "    width: 24px !important;",
    "    height: 24px !important;",
    "    min-width: 24px !important;",
    "    min-height: 24px !important;",
    "    max-width: 24px !important;",
    "    max-height: 24px !important;",
    "    border: none !important;",
    "    background: transparent !important;",
    "    box-shadow: none !important;",
    "  }",
    "  .mx_MessageComposer .mx_VoiceRecordComposerTile_stop {",
    "    width: 20px !important;",
    "    height: 20px !important;",
    "    min-width: 20px !important;",
    "    min-height: 20px !important;",
    "    border: 2px solid rgba(255,255,255,.35) !important;",
    "    border-radius: 32px !important;",
    "    background: transparent !important;",
    "    box-shadow: none !important;",
    "  }",
    "  .mx_MessageComposer .mx_VoiceMessagePrimaryContainer {",
    "    flex: 1 1 auto !important;",
    "    min-width: 72px !important;",
    "    height: 32px !important;",
    "    border-radius: 12px !important;",
    "    background: rgba(255,255,255,.08) !important;",
    "  }",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_delete) .mx_MessageComposer_sendMessage,",
    "  .mx_MessageComposer:has(.mx_VoiceRecordComposerTile_stop) .mx_MessageComposer_sendMessage,",
    "  .mx_MessageComposer:has(.mx_VoiceMessagePrimaryContainer) .mx_MessageComposer_sendMessage,",
    "  .mx_MessageComposer[data-jingepi-recording='1'] .mx_MessageComposer_sendMessage {",
    "    position: relative !important;",
    "    right: auto !important;",
    "    top: auto !important;",
    "    transform: none !important;",
    "  }",
    "  .mx_MessageComposer .mx_WysiwygComposer_Editor_content_placeholder::before,",
    "  .mx_MessageComposer .mx_BasicMessageComposer_input:empty::before,",
    "  .mx_MessageComposer [data-placeholder]:empty::before {",
    "    white-space: nowrap !important;",
    "    overflow: visible !important;",
    "    text-overflow: clip !important;",
    "  }",
    "}",

    "/* ---- 侧栏搜索：垂直居中 + focus 细金边（禁白框） ---- */",
    ".mx_RoomListSearch input,",
    ".mx_RoomListHeader input[type='text'],",
    ".mx_RoomListHeader input[type='search'] {",
    "  height: 36px !important;",
    "  min-height: 36px !important;",
    "  padding: 0 12px !important;",
    "  line-height: 36px !important;",
    "  box-sizing: border-box !important;",
    "  outline: none !important;",
    "}",
    ".mx_RoomListSearch input:focus,",
    ".mx_RoomListSearch input:focus-visible,",
    ".mx_RoomListHeader input:focus {",
    "  outline: none !important;",
    "  border: 1px solid rgba(240,185,11,.55) !important;",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.28), inset 0 -1px 0 rgba(0,0,0,.25) !important;",
    "}",
    ".mx_RoomListSearch .mx_Field:focus-within,",
    ".mx_RoomListSearch form:focus-within {",
    "  outline: none !important;",
    "  border: none !important;",
    "  box-shadow: none !important;",
    "  background: transparent !important;",
    "}",

    "/* ---- 房间信息打开：隐藏顶栏「更多」⋯（避免叠到右侧搜索） ---- */",
    "body[data-jingepi-room-info-open='1'] #jingepi-room-header-more,",
    "body[data-jingepi-room-info-open='1'] #jingepi-room-header-more-panel,",
    "body:has(.mx_RoomSummaryCard) #jingepi-room-header-more,",
    "body:has(.mx_RoomSummaryCard) #jingepi-room-header-more-panel,",
    "body:has(.mx_RightPanel .mx_RoomSummaryCard) #jingepi-room-header-more,",
    "body:has(.mx_RightPanel .mx_BaseCard) #jingepi-room-header-more,",
    "body:has(.mx_RightPanel .mx_RoomInfo) #jingepi-room-header-more {",
    "  display: none !important;",
    "  pointer-events: none !important;",
    "  visibility: hidden !important;",
    "  opacity: 0 !important;",
    "}",

    "/* ---- 任意 Dialog 打开：隐藏展开/收起，避免压在设置/创建空间上 ---- */",
    "body:has(.mx_Dialog_wrapper) #jingepi-left-panel-toggle,",
    "body:has(.mx_Dialog_background) #jingepi-left-panel-toggle,",
    "body:has(.mx_SettingsDialog) #jingepi-left-panel-toggle,",
    "body:has(.mx_UserSettingsDialog) #jingepi-left-panel-toggle {",
    "  display: none !important;",
    "  pointer-events: none !important;",
    "  visibility: hidden !important;",
    "}",

    "/* ---- 左侧栏折叠：不再 CSS 压 width:0（改由 Element 原生 collapse） ---- */",
    "body[data-jingepi-roomlist-collapsed='1']:not(.jingepi-panel-expanding) [data-jingepi-collapsed-col='1'] {",
    "  pointer-events: none;",
    "}",
    "/* 窄屏：列表全屏时 Space 默认藏；点「空间」Tab 再显全屏列表（主题 CSS 主控） */",
    "@media screen and (max-width: 900px) {",
    "  body[data-jingepi-roomlist-collapsed='1']:not(.jingepi-panel-expanding):not([data-jingepi-mobile-roomlist='1']) .mx_SpacePanel {",
    "    /* 聊天态：Space 底栏显隐交给 syncMobileSpaceBar / 主题 CSS */",
    "  }",
    "  /* 零宽藏左侧分割条（勿 display:none，expand 仍需节点） */",
    "  .mx_MatrixChat > [role='separator'],",
    "  .mx_MainSplit > [role='separator'],",
    "  .mx_LeftPanel > [role='separator'],",
    "  .mx_LeftPanel_wrapper > [role='separator'],",
    "  [role='separator'][data-separator-type] {",
    "    width: 0 !important;",
    "    min-width: 0 !important;",
    "    max-width: 0 !important;",
    "    flex: 0 0 0 !important;",
    "    opacity: 0 !important;",
    "    pointer-events: none !important;",
    "    border: none !important;",
    "    background: transparent !important;",
    "    overflow: hidden !important;",
    "  }",
    "  #jingepi-left-panel-toggle {",
    "    display: none !important;",
    "    visibility: hidden !important;",
    "    pointer-events: none !important;",
    "  }",
    "  #jingepi-space-sheet {",
    "    position: fixed !important;",
    "    inset: 0 !important;",
    "    z-index: 10050 !important;",
    "    pointer-events: none !important;",
    "  }",
    "  #jingepi-space-sheet #jingepi-mobile-space-backdrop {",
    "    pointer-events: auto !important;",
    "    z-index: 0 !important;",
    "  }",
    "  /* 空间列表页：全屏竖向列表（非底栏图标抽屉）；细则见主题 CSS */",
    "  body[data-jingepi-mobile-spaces='1'] #jingepi-space-sheet > .mx_SpacePanel,",
    "  body[data-jingepi-mobile-spaces='1'] #jingepi-space-sheet > .mx_SpacePanel.collapsed,",
    "  body[data-jingepi-mobile-spaces='1'] .mx_SpacePanel,",
    "  body[data-jingepi-mobile-spaces='1'] .mx_SpacePanel.collapsed {",
    "    display: flex !important;",
    "    flex-direction: column !important;",
    "    visibility: visible !important;",
    "    opacity: 1 !important;",
    "    pointer-events: auto !important;",
    "    position: absolute !important;",
    "    inset: 0 !important;",
    "    width: 100% !important;",
    "    max-width: 100vw !important;",
    "    height: 100% !important;",
    "    max-height: none !important;",
    "    z-index: 1 !important;",
    "    overflow-x: hidden !important;",
    "    overflow-y: auto !important;",
    "    backdrop-filter: none !important;",
    "    -webkit-backdrop-filter: none !important;",
    "    filter: none !important;",
    "  }",
    "  body[data-jingepi-mobile-spaces='1'] .mx_SpacePanel .mx_SpaceButton_name {",
    "    display: block !important;",
    "  }",
    "}",
    "body:not(.jingepi-panel-expanding) [role='separator'][data-separator-type='bar'] {",
    "  width: 0 !important;",
    "  min-width: 0 !important;",
    "  max-width: 0 !important;",
    "  flex: 0 0 0 !important;",
    "  opacity: 0 !important;",
    "  pointer-events: none !important;",
    "  border: none !important;",
    "  background: transparent !important;",
    "  overflow: hidden !important;",
    "}",
    "[role='separator'][data-separator-type='bar'] svg {",
    "  display: none !important;",
    "}",
    "/* left/top 由 JS 写；translateX(-50%) 锚在窄栏/Home 中心，勿贴右缘甩进主区 */",
    "#jingepi-left-panel-toggle {",
    "  position: fixed;",
    "  z-index: 150;",
    "  display: inline-flex;",
    "  flex-direction: column;",
    "  align-items: center;",
    "  justify-content: center;",
    "  box-sizing: border-box;",
    "  min-width: 28px;",
    "  min-height: 28px;",
    "  height: auto;",
    "  padding: 5px 8px;",
    "  margin: 0;",
    "  border: 1px solid rgba(240,185,11,.42);",
    "  border-radius: 8px;",
    "  background: linear-gradient(155deg, rgba(255,255,255,.1) 0%, rgba(80,80,86,.08) 38%, rgba(0,0,0,.16) 100%), rgba(36,36,40,.45);",
    "  color: " + GOLD + ";",
    "  font-size: 12px;",
    "  font-weight: 600;",
    "  line-height: 1.15;",
    "  letter-spacing: 0.02em;",
    "  text-align: center;",
    "  white-space: normal;",
    "  cursor: pointer;",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.28), inset 0 -1px 0 rgba(0,0,0,.25), 0 8px 20px rgba(0,0,0,.28);",
    "  backdrop-filter: blur(14px) saturate(150%);",
    "  -webkit-backdrop-filter: blur(14px) saturate(150%);",
    "  transform: translateX(-50%);",
    "  pointer-events: auto;",
    "}",
    "#jingepi-left-panel-toggle[data-jingepi-panel-state='collapsed'] {",
    "  min-width: 72px;",
    "  max-width: 84px;",
    "  padding: 5px 6px;",
    "  font-size: 10px;",
    "  line-height: 1.2;",
    "}",
    "#jingepi-left-panel-toggle[data-jingepi-panel-state='expanded'] {",
    "  min-width: 40px;",
    "  font-size: 12px;",
    "  line-height: 1;",
    "  white-space: nowrap;",
    "}",
    "#jingepi-left-panel-toggle .jingepi-toggle-line {",
    "  display: block;",
    "  white-space: nowrap;",
    "  line-height: inherit;",
    "}",
    "#jingepi-left-panel-toggle:hover {",
    "  background: linear-gradient(155deg, rgba(255,255,255,.14) 0%, rgba(90,90,96,.12) 38%, rgba(0,0,0,.18) 100%), rgba(44,44,48,.5);",
    "  border-color: " + GOLD + ";",
    "  color: " + GOLD_LIGHT + ";",
    "  box-shadow: inset 0 1px 0 rgba(255,255,255,.32), 0 0 16px rgba(240,185,11,.2);",
    "}",
    /* 更多菜单挂 body：fixed + 超高 z，避免 header 层叠/裁切挡点击 */
    "#jingepi-room-header-more-panel {",
    "  z-index: 10050 !important;",
    "}",

    "/* 窄屏：房间列表项「更多/通知」常显，避免依赖 :hover（触控首点易误进房） */",
    "@media (max-width: 900px) {",
    "  body[data-jingepi-qq-list='1'] .mx_RoomListItemView [class*='_hoverMenu_'],",
    "  body[data-jingepi-mobile-roomlist='1'] .mx_RoomListItemView [class*='_hoverMenu_'] {",
    "    display: flex !important;",
    "    align-items: center !important;",
    "    opacity: 1 !important;",
    "    visibility: visible !important;",
    "    pointer-events: auto !important;",
    "    position: relative !important;",
    "    width: auto !important;",
    "    height: auto !important;",
    "    flex: 0 0 auto !important;",
    "  }",
    "  body[data-jingepi-qq-list='1'] .mx_RoomListItemView [class*='_hoverMenu_'] > button,",
    "  body[data-jingepi-mobile-roomlist='1'] .mx_RoomListItemView [class*='_hoverMenu_'] > button {",
    "    pointer-events: auto !important;",
    "    min-width: 32px !important;",
    "    min-height: 32px !important;",
    "  }",
    "  body[data-jingepi-qq-list='1'] .mx_RoomListItemView [class*='_notificationDecoration_'],",
    "  body[data-jingepi-mobile-roomlist='1'] .mx_RoomListItemView [class*='_notificationDecoration_'] {",
    "    display: none !important;",
    "  }",
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
    /验证此设备|验证此会话|Verify this device|Verify this session|Back up your chats|备份聊天|密钥存储|key storage|Turn on key storage|开启密钥存储|Allow key storage|允许密钥存储|out of sync|不同步|identity|数字身份|recovery key|恢复密钥|Secure Backup|安全备份|端到端加密自动备份|自动备份|Cryptography|密码学|Set up recovery|设置恢复|Forgot recovery|忘记恢复|mobile.?app|下载.?应用|desktop site|does not work on mobile|改用手机|使用手机版|Use the app|Get the app/i;

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
  var headerMoreActivating = false;
  var headerMoreIgnoreOutsideUntil = 0;

  function headerBtnLabel(btn) {
    return (btn.getAttribute("aria-label") || btn.getAttribute("title") || "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function isHeaderExcludedBtn(btn) {
    if (!btn || btn.getAttribute("data-jingepi-header-more") === "1") return true;
    if (btn.closest("#jingepi-room-header-more")) return true;
    if (btn.closest("#jingepi-room-header-more-panel")) return true;
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

  function findCurrentRoomHeader() {
    return (
      document.querySelector("header.mx_RoomHeader") ||
      document.querySelector(".mx_RoomHeader") ||
      document.querySelector(".mx_LegacyRoomHeader")
    );
  }

  function collectHeaderActionButtons(header) {
    var found = {};
    var candidates = [];
    if (!header) return found;
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

  function getHeaderMorePanel() {
    return document.getElementById("jingepi-room-header-more-panel");
  }

  function getHeaderMoreBtn() {
    return document.querySelector(
      "#jingepi-room-header-more > button.jingepi-room-header-more-btn"
    );
  }

  function positionHeaderMorePanel() {
    var panel = getHeaderMorePanel();
    var btn = getHeaderMoreBtn();
    if (!panel || !btn || panel.getAttribute("data-open") !== "1") return;
    var rect = btn.getBoundingClientRect();
    var pad = 6;
    var panelW = Math.max(panel.offsetWidth || 168, 168);
    var left = rect.right - panelW;
    if (left < 8) left = 8;
    if (left + panelW > window.innerWidth - 8) {
      left = Math.max(8, window.innerWidth - panelW - 8);
    }
    var top = rect.bottom + pad;
    panel.style.left = Math.round(left) + "px";
    panel.style.top = Math.round(top) + "px";
    panel.style.right = "auto";
    panel.style.bottom = "auto";
  }

  function openHeaderMorePanel() {
    var panel = getHeaderMorePanel();
    var btn = getHeaderMoreBtn();
    if (!panel || !btn) return;
    if (panel.parentElement !== document.body) {
      document.body.appendChild(panel);
    }
    panel.setAttribute("data-open", "1");
    btn.setAttribute("aria-expanded", "true");
    positionHeaderMorePanel();
    headerMoreIgnoreOutsideUntil = Date.now() + 350;
    requestAnimationFrame(positionHeaderMorePanel);
  }

  function closeHeaderMorePanel() {
    var panel = getHeaderMorePanel();
    var btn = getHeaderMoreBtn();
    if (panel) {
      panel.removeAttribute("data-open");
      panel.style.left = "";
      panel.style.top = "";
    }
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  /**
   * 触发被藏起的原顶栏按钮。
   * 原 display:none + 瞬时 restore 会导致 React onClick 吃不到；
   * 现改为视觉隐藏节点上直接 click，并尝试派发指针序列 / 调 React props。
   */
  function fireDomClick(target) {
    if (!target) return false;
    try {
      if (typeof target.focus === "function") {
        try {
          target.focus({ preventScroll: true });
        } catch (_f) {
          target.focus();
        }
      }
    } catch (_e0) {
      /* ignore */
    }

    var rect = target.getBoundingClientRect();
    var cx = rect.left + Math.max(rect.width, 1) / 2;
    var cy = rect.top + Math.max(rect.height, 1) / 2;
    if (!isFinite(cx) || !isFinite(cy) || rect.width < 1) {
      cx = 8;
      cy = 8;
    }
    var common = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: cx,
      clientY: cy,
      button: 0,
      buttons: 1,
      pointerId: 1,
      pointerType: "mouse",
      isPrimary: true,
    };
    try {
      if (typeof PointerEvent === "function") {
        target.dispatchEvent(new PointerEvent("pointerdown", common));
        target.dispatchEvent(
          new PointerEvent(
            "pointerup",
            Object.assign({}, common, { buttons: 0 })
          )
        );
      }
      target.dispatchEvent(new MouseEvent("mousedown", common));
      target.dispatchEvent(
        new MouseEvent("mouseup", Object.assign({}, common, { buttons: 0 }))
      );
      target.dispatchEvent(
        new MouseEvent("click", Object.assign({}, common, { buttons: 0 }))
      );
    } catch (_e1) {
      /* ignore */
    }
    try {
      if (typeof target.click === "function") target.click();
    } catch (_e2) {
      /* ignore */
    }

    /* React 17+：直接调 props.onClick 作为兜底 */
    try {
      var keys = Object.keys(target);
      for (var i = 0; i < keys.length; i++) {
        var k = keys[i];
        if (
          k.indexOf("__reactProps$") === 0 ||
          k.indexOf("__reactEventHandlers$") === 0
        ) {
          var props = target[k];
          if (props && typeof props.onClick === "function") {
            props.onClick({
              type: "click",
              target: target,
              currentTarget: target,
              preventDefault: function () {},
              stopPropagation: function () {},
              nativeEvent: { isTrusted: false },
            });
            return true;
          }
        }
      }
    } catch (_e3) {
      /* ignore */
    }
    return true;
  }

  function activateHeaderActionByKey(actionKey) {
    var header = findCurrentRoomHeader();
    if (!header || !actionKey) return;
    headerMoreActivating = true;
    var found = collectHeaderActionButtons(header);
    var target = found[actionKey];
    if (!target || !target.isConnected) {
      headerMoreActivating = false;
      return;
    }

    var unmarked = [];
    var el = target;
    while (el && el !== header.parentElement) {
      if (el.getAttribute && el.getAttribute("data-jingepi-header-overflow") === "1") {
        unmarked.push(el);
        el.removeAttribute("data-jingepi-header-overflow");
      }
      el = el.parentElement;
    }

    var prevCss = target.getAttribute("style") || "";
    target.style.setProperty("position", "fixed", "important");
    target.style.setProperty("left", "8px", "important");
    target.style.setProperty("top", "8px", "important");
    target.style.setProperty("width", "36px", "important");
    target.style.setProperty("height", "36px", "important");
    target.style.setProperty("display", "inline-flex", "important");
    target.style.setProperty("visibility", "visible", "important");
    target.style.setProperty("opacity", "0", "important");
    target.style.setProperty("pointer-events", "auto", "important");
    target.style.setProperty("clip", "auto", "important");
    target.style.setProperty("clip-path", "none", "important");
    target.style.setProperty("z-index", "2147483001", "important");

    function restore() {
      try {
        if (prevCss) target.setAttribute("style", prevCss);
        else target.removeAttribute("style");
        for (var i = 0; i < unmarked.length; i++) {
          if (unmarked[i] && unmarked[i].isConnected) {
            unmarked[i].setAttribute("data-jingepi-header-overflow", "1");
          }
        }
      } finally {
        headerMoreActivating = false;
      }
    }

    fireDomClick(target);
    /* 给 React 状态更新留时间；期间 headerMoreActivating 挡住 suppress 回藏 */
    setTimeout(restore, 160);
  }

  function ensureHeaderMoreOutsideClose() {
    if (headerMoreOutsideBound) return;
    headerMoreOutsideBound = true;
    document.addEventListener(
      "pointerdown",
      function (ev) {
        if (Date.now() < headerMoreIgnoreOutsideUntil) return;
        var panel = getHeaderMorePanel();
        var wrap = document.getElementById("jingepi-room-header-more");
        if (!panel || panel.getAttribute("data-open") !== "1") return;
        var t = ev.target;
        if (panel.contains(t)) return;
        if (wrap && wrap.contains(t)) return;
        closeHeaderMorePanel();
      },
      true
    );
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeHeaderMorePanel();
    });
    window.addEventListener("resize", function () {
      positionHeaderMorePanel();
    });
  }

  function bindHeaderMorePanelDelegation(panel) {
    if (!panel || panel.getAttribute("data-jingepi-bound") === "1") return;
    panel.setAttribute("data-jingepi-bound", "1");
    function stop(ev) {
      ev.stopPropagation();
    }
    panel.addEventListener("pointerdown", stop, true);
    panel.addEventListener("mousedown", stop, true);
    panel.addEventListener("mouseup", stop, true);
    panel.addEventListener("click", function (ev) {
      var item =
        ev.target && ev.target.closest
          ? ev.target.closest("button[data-jingepi-action-key]")
          : null;
      if (!item || !panel.contains(item)) return;
      ev.preventDefault();
      ev.stopPropagation();
      if (item.disabled) return;
      var key = item.getAttribute("data-jingepi-action-key");
      closeHeaderMorePanel();
      setTimeout(function () {
        activateHeaderActionByKey(key);
      }, 16);
    });
  }

  function ensureHeaderMoreUi(header) {
    var wrap = document.getElementById("jingepi-room-header-more");
    if (wrap && !header.contains(wrap)) {
      var orphanPanel = getHeaderMorePanel();
      if (orphanPanel) orphanPanel.remove();
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
      function stopHeaderMoreBubble(ev) {
        try {
          ev.stopPropagation();
        } catch (_eStop) {
          /* ignore */
        }
      }
      /* 只 stopPropagation，勿 preventDefault(pointerdown)，否则会吞掉后续 click */
      btn.addEventListener("pointerdown", stopHeaderMoreBubble, true);
      btn.addEventListener("mousedown", stopHeaderMoreBubble, true);
      btn.addEventListener("click", function (ev) {
        try {
          ev.preventDefault();
        } catch (_ePrev) {
          /* ignore */
        }
        stopHeaderMoreBubble(ev);
        var open = panel.getAttribute("data-open") === "1";
        if (open) {
          closeHeaderMorePanel();
        } else {
          openHeaderMorePanel();
        }
      });
      wrap.appendChild(btn);
      /* 面板始终挂 body，避免 header 层叠/裁切；rebuild 用 getElementById */
      if (panel.parentElement !== document.body) {
        document.body.appendChild(panel);
      }
      bindHeaderMorePanelDelegation(panel);
    } else {
      var existing = getHeaderMorePanel();
      if (existing && existing.parentElement !== document.body) {
        document.body.appendChild(existing);
      }
      bindHeaderMorePanelDelegation(existing);
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
    var panel = getHeaderMorePanel();
    if (!panel) return;
    if (panel.parentElement !== document.body) {
      document.body.appendChild(panel);
    }
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
    /* 打开时不重建，避免指针落在被销毁的菜单项上 */
    if (panel.getAttribute("data-open") === "1") {
      positionHeaderMorePanel();
      return;
    }
    if (
      panel.getAttribute("data-jingepi-sig") === sig &&
      panel.childNodes.length
    ) {
      return;
    }
    panel.setAttribute("data-jingepi-sig", sig);
    /* 只清子项；面板上的 click 委托仍有效，勿重复 bind */
    panel.textContent = "";

    for (var j = 0; j < order.length; j++) {
      var k = order[j];
      var src = found[k];
      if (!src) continue;
      var item = document.createElement("button");
      item.type = "button";
      item.setAttribute("role", "menuitem");
      item.setAttribute("data-jingepi-action-key", k);
      var label = headerBtnLabel(src);
      var defTitle = titles[k];
      if (!label || !classifyHeaderAction(src)) label = defTitle;
      item.textContent = label || defTitle;
      var disabled =
        !!src.disabled || src.getAttribute("aria-disabled") === "true";
      if (disabled) item.disabled = true;
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
    /* 必须锚定左侧栏旁的分隔线；勿命中右侧栏等其它 role=separator（否则误判 bar→整列压 0） */
    var roots = [
      document.querySelector(".mx_LeftPanel"),
      document.querySelector(".mx_LeftPanel_wrapper"),
      document.querySelector(".mx_MainSplit"),
    ];
    var i;
    for (i = 0; i < roots.length; i++) {
      var root = roots[i];
      if (!root) continue;
      var local =
        root.querySelector("[role='separator'][data-separator-type]") ||
        root.querySelector(
          "[role='separator'][aria-label*='拖动'], [role='separator'][aria-label*='展开'], [role='separator'][aria-label*='expand'], [role='separator'][aria-label*='Expand']"
        );
      if (local) return local;
    }
    var all = document.querySelectorAll(
      "[role='separator'][data-separator-type]"
    );
    for (i = 0; i < all.length; i++) {
      var sep = all[i];
      var prev = sep.previousElementSibling;
      if (
        prev &&
        (prev.classList.contains("mx_LeftPanel") ||
          prev.classList.contains("mx_LeftPanel_wrapper") ||
          (prev.querySelector &&
            prev.querySelector(
              ".mx_SpacePanel, .mx_RoomListPanel, .mx_LeftPanel"
            )))
      ) {
        return sep;
      }
    }
    return null;
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

  var leftPanelExpanding = false;
  var leftPanelExpandTimer = 0;
  var leftPanelForcedCollapsed = false;
  /* 仅用户刚点「收起」后短暂为 true；定时器/Observer 不得据此 crush */
  var leftPanelUserCollapseArmed = false;
  var leftPanelCollapseArmTimer = 0;
  var LEFT_PANEL_TOP_PAD = 38;
  var JINGEPI_ROOMLIST_DBG =
    typeof location !== "undefined" &&
    /(?:\?|&)jingepi_roomlist_dbg=1(?:&|$)/.test(location.search || "");

  function jingepiRoomListLog() {
    if (!JINGEPI_ROOMLIST_DBG) return;
    try {
      var args = Array.prototype.slice.call(arguments);
      args.unshift("[jingepi-roomlist]");
      console.log.apply(console, args);
    } catch (_e) {
      /* ignore */
    }
  }

  function armUserCollapse() {
    leftPanelUserCollapseArmed = true;
    if (leftPanelCollapseArmTimer) clearTimeout(leftPanelCollapseArmTimer);
    leftPanelCollapseArmTimer = setTimeout(function () {
      leftPanelUserCollapseArmed = false;
      leftPanelCollapseArmTimer = 0;
      jingepiRoomListLog("userCollapseArmed expired");
    }, 1800);
    jingepiRoomListLog("userCollapseArmed");
  }

  function disarmUserCollapse() {
    leftPanelUserCollapseArmed = false;
    if (leftPanelCollapseArmTimer) {
      clearTimeout(leftPanelCollapseArmTimer);
      leftPanelCollapseArmTimer = 0;
    }
  }

  function setRoomListCollapsedFlag(on) {
    leftPanelForcedCollapsed = !!on;
    jingepiRoomListLog("setCollapsed", !!on, {
      armed: leftPanelUserCollapseArmed,
      expanding: leftPanelExpanding,
    });
    if (!document.body) return;
    if (on) {
      document.body.setAttribute("data-jingepi-roomlist-collapsed", "1");
      document.body.classList.add("jingepi-panel-collapsed");
    } else {
      document.body.removeAttribute("data-jingepi-roomlist-collapsed");
      document.body.classList.remove("jingepi-panel-collapsed");
    }
  }

  function clearCollapsedColStyles(el) {
    if (!el || !el.style) return;
    el.style.removeProperty("width");
    el.style.removeProperty("min-width");
    el.style.removeProperty("max-width");
    el.style.removeProperty("flex");
    el.style.removeProperty("flex-basis");
    el.style.removeProperty("flex-grow");
    el.style.removeProperty("flex-shrink");
    el.style.removeProperty("overflow");
    el.style.removeProperty("opacity");
    el.style.removeProperty("visibility");
    el.style.removeProperty("padding");
    el.style.removeProperty("margin");
    el.style.removeProperty("border");
    el.style.removeProperty("border-right");
    el.style.removeProperty("pointer-events");
    el.style.removeProperty("background");
    el.style.removeProperty("position");
    el.style.removeProperty("left");
    el.style.removeProperty("right");
    el.style.removeProperty("bottom");
    el.style.removeProperty("top");
    el.style.removeProperty("display");
    el.style.removeProperty("height");
    el.style.removeProperty("min-height");
    el.style.removeProperty("max-height");
    el.removeAttribute("data-jingepi-collapsed-col");
  }

  function clearSpacePanelHideInline() {
    var space = document.querySelector(".mx_SpacePanel");
    if (!space || !space.style) return;
    clearCollapsedColStyles(space);
  }

  /* ---- 窄屏 QQ：列表页 ↔ 聊天页 ---- */
  var mobileQqLastMode = "";
  var mobileQqHashBound = false;
  var mobileQqListClickBound = false;
  var roomListAuxGuardBound = false;
  /* 点「更多/通知」等控件时，短暂禁止进房（防列表项 button 冒泡 openRoom） */
  var suppressRoomEnterUntil = 0;
  var blockOpenRoomUntil = 0;
  var blockOpenRoomSavedHash = "#/home";
  var blockOpenRoomClearTimer = 0;
  var historyNavGuardInstalled = false;
  /* 返回处理中：忽略重复点击，且禁止 observer/sync 改 hash / 反复展开 */
  var mobileQqBackLock = false;
  var mobileQqBackLockTimer = 0;

  function armSuppressRoomEnter(ms) {
    var until = Date.now() + (ms || 1200);
    if (until > suppressRoomEnterUntil) suppressRoomEnterUntil = until;
  }

  function isSuppressRoomEnterArmed() {
    return Date.now() < suppressRoomEnterUntil;
  }

  function isBlockOpenRoomArmed() {
    return Date.now() < blockOpenRoomUntil;
  }

  function clearBlockOpenRoomFlag() {
    if (isBlockOpenRoomArmed()) return;
    try {
      if (document.body) document.body.removeAttribute("data-jingepi-block-open-room");
    } catch (_e) {
      /* ignore */
    }
  }

  /** 短时禁止切到房间（桌面+窄屏）；配合 hash/history 回退 */
  function armBlockOpenRoom(ms) {
    var dur = typeof ms === "number" ? ms : 480;
    var until = Date.now() + dur;
    if (until > blockOpenRoomUntil) blockOpenRoomUntil = until;
    armSuppressRoomEnter(Math.max(dur + 200, 1400));
    try {
      var h = location.hash || "#/home";
      if (!/#\/room\//.test(h) && !/#\/user\//.test(h)) {
        blockOpenRoomSavedHash = h || "#/home";
      }
    } catch (_eHash) {
      blockOpenRoomSavedHash = "#/home";
    }
    try {
      if (document.body) {
        document.body.setAttribute("data-jingepi-block-open-room", "1");
      }
    } catch (_eBody) {
      /* ignore */
    }
    if (blockOpenRoomClearTimer) clearTimeout(blockOpenRoomClearTimer);
    blockOpenRoomClearTimer = setTimeout(clearBlockOpenRoomFlag, dur + 80);
  }

  function isRoomNavHash(h) {
    return /#\/room\//.test(h || "") || /#\/user\//.test(h || "");
  }

  /** 点更多/通知后若仍被 openRoom 改路由：立刻退回列表 hash（桌面也要） */
  function revertBlockedRoomNavigation() {
    if (!isBlockOpenRoomArmed() && !isSuppressRoomEnterArmed()) return false;
    var h = "";
    try {
      h = location.hash || "";
    } catch (_e) {
      return false;
    }
    if (!isRoomNavHash(h)) return false;
    var back = blockOpenRoomSavedHash || "#/home";
    try {
      if (isMobileViewport() && !mobileQqBackLock) armMobileQqBackLock(900);
      history.replaceState(null, "", location.pathname + location.search + back);
      if (document.body && isMobileViewport()) {
        document.body.setAttribute("data-jingepi-qq-list", "1");
        document.body.removeAttribute("data-jingepi-qq-chat");
        document.body.setAttribute("data-jingepi-mobile-roomlist", "1");
        document.body.removeAttribute("data-jingepi-chatting");
        mobileQqLastMode = "list";
        setTimeout(function () {
          forceMobileListPanelGeometry();
          ensureMobileTabBar(true);
          syncMobileQqPages();
        }, 40);
      }
      return true;
    } catch (_e2) {
      try {
        location.hash = back;
      } catch (_e3) {
        /* ignore */
      }
      return false;
    }
  }

  function installHistoryNavGuard() {
    if (historyNavGuardInstalled) return;
    historyNavGuardInstalled = true;
    var origPush = history.pushState;
    var origReplace = history.replaceState;
    function wrapHist(orig) {
      return function (state, title, url) {
        if (isBlockOpenRoomArmed() && url != null) {
          var s = String(url);
          if (isRoomNavHash(s) || /\/room\//.test(s) || /\/user\//.test(s)) {
            return state;
          }
        }
        return orig.apply(this, arguments);
      };
    }
    try {
      history.pushState = wrapHist(origPush);
      history.replaceState = wrapHist(origReplace);
    } catch (_eHist) {
      /* ignore */
    }
  }

  /**
   * 点在「不应进房」的控件上：房间列表项内更多/通知、菜单、顶栏更多、Tab、返回等。
   * 整行 .mx_RoomListItemView 本身是进房 button（aria-label=打开房间），不算 aux。
   * 注意：勿把整个 #jingepi-space-sheet 当 chrome——点空间本体要能选中空间；
   * 仅空间行「更多 / 折叠」与 sheet 顶栏/遮罩算 chrome。
   */
  function isRoomNavChromeTarget(t) {
    if (!t || !t.closest) return false;
    if (
      t.closest(
        "#jingepi-mobile-tabbar, #jingepi-mobile-back, #jingepi-room-header-more, #jingepi-room-header-more-panel, #jingepi-composer-more, #jingepi-space-sheet-header, #jingepi-mobile-space-backdrop, #jingepi-left-panel-toggle"
      )
    ) {
      return true;
    }
    if (
      t.closest(
        ".mx_SpaceButton_menuButton, .mx_SpaceButton_toggleCollapse, .mx_SpacePanel_toggleCollapse"
      )
    ) {
      return true;
    }
    if (
      t.closest(
        '[role="menu"], [data-radix-menu-content], .mx_IconizedContextMenu, .mx_Dialog, .mx_ContextualMenu, .mx_SpacePanel_contextMenu'
      )
    ) {
      return true;
    }
    var item = t.closest(
      ".mx_RoomListItemView, .mx_RoomTile, [data-testid='room-list-item']"
    );
    if (item) {
      if (t === item) return false;
      /* Compound 悬停菜单：更多选项 + 通知选项 */
      if (t.closest('[class*="_hoverMenu_"]')) return true;
      if (t.closest('[data-jingepi-aux-native="1"]')) return true;
      var nested = t.closest("button, [role='button'], [aria-haspopup]");
      if (nested && nested !== item && item.contains(nested)) {
        var lab = (
          (nested.getAttribute("aria-label") || "") +
          " " +
          (nested.getAttribute("title") || "")
        ).replace(/\s+/g, " ");
        if (/打开房间|Open room/i.test(lab)) return false;
        if (
          /更多选项|More options|通知选项|Notification options|更多|More|通知|Notification|选项|Options|⋯|\.\.\./i.test(
            lab
          )
        ) {
          return true;
        }
        /* 列表项内任意嵌套 button（非法套 button）都不进房 */
        return true;
      }
      return false;
    }
    var chrome = t.closest("button, [role='button'], [aria-haspopup]");
    if (!chrome) return false;
    if (chrome.classList && chrome.classList.contains("mx_RoomListItemView")) {
      return false;
    }
    var label = (
      (chrome.getAttribute("aria-label") || "") +
      " " +
      (chrome.getAttribute("title") || "") +
      " " +
      (chrome.textContent || "")
    )
      .replace(/\s+/g, " ")
      .trim();
    if (/打开房间|Open room/i.test(label)) return false;
    return /更多选项|More options|通知选项|Notification options|更多|More|选项|Options|通知|Notification|⋯|\.\.\./i.test(
      label
    );
  }

  function getReactFiber(el) {
    if (!el) return null;
    try {
      for (var k in el) {
        if (k && k.indexOf("__reactFiber$") === 0) return el[k];
      }
    } catch (_e) {
      /* ignore */
    }
    return null;
  }

  function getReactProps(el) {
    if (!el) return null;
    try {
      for (var k in el) {
        if (k && k.indexOf("__reactProps$") === 0) return el[k];
      }
    } catch (_e) {
      /* ignore */
    }
    return null;
  }

  function wrapOpenRoomGuard(fn) {
    if (fn && fn.__jingepiOpenGuard) return fn;
    var wrapped = function (ev) {
      var t = null;
      try {
        t =
          (ev && (ev.target || (ev.nativeEvent && ev.nativeEvent.target))) || null;
      } catch (_eT) {
        t = null;
      }
      if (
        isRoomNavChromeTarget(t) ||
        isBlockOpenRoomArmed() ||
        isSuppressRoomEnterArmed()
      ) {
        try {
          if (ev && typeof ev.stopPropagation === "function") ev.stopPropagation();
        } catch (_eStop) {
          /* ignore */
        }
        return;
      }
      if (typeof fn === "function") return fn.apply(this, arguments);
    };
    wrapped.__jingepiOpenGuard = 1;
    return wrapped;
  }

  function wrapAuxStopPropagation(fn) {
    if (fn && fn.__jingepiAuxStop) return fn;
    var wrapped = function (ev) {
      var ret;
      try {
        if (typeof fn === "function") ret = fn.apply(this, arguments);
      } finally {
        try {
          if (ev && typeof ev.stopPropagation === "function") ev.stopPropagation();
        } catch (_eStop) {
          /* ignore */
        }
      }
      return ret;
    };
    wrapped.__jingepiAuxStop = 1;
    return wrapped;
  }

  function patchFiberHandlers(fiber, names, wrapFn, maxDepth) {
    var f = fiber;
    var depth = typeof maxDepth === "number" ? maxDepth : 12;
    for (var d = 0; d < depth && f; d++) {
      var props = f.memoizedProps || f.pendingProps;
      if (props) {
        for (var i = 0; i < names.length; i++) {
          var name = names[i];
          if (typeof props[name] === "function") {
            var next = wrapFn(props[name]);
            if (next !== props[name]) props[name] = next;
          }
        }
        try {
          f.memoizedProps = props;
          if (f.pendingProps && f.pendingProps !== props) {
            f.pendingProps = props;
          }
        } catch (_eSet) {
          /* ignore */
        }
      }
      f = f.return;
    }
  }

  /** 在列表行 fiber 上吞掉 openRoom（点更多/通知时） */
  function patchRoomListItemOpenGuard(item) {
    if (!item || !item.matches) return;
    if (
      !item.matches(
        ".mx_RoomListItemView, .mx_RoomTile, [data-testid='room-list-item']"
      )
    ) {
      return;
    }
    var names = [
      "onClick",
      "onPointerDown",
      "onPointerUp",
      "onMouseDown",
      "onMouseUp",
      "onKeyDown",
    ];
    patchFiberHandlers(getReactFiber(item), names, wrapOpenRoomGuard, 14);
    var domProps = getReactProps(item);
    if (domProps) {
      for (var i = 0; i < names.length; i++) {
        var n = names[i];
        if (typeof domProps[n] === "function") {
          domProps[n] = wrapOpenRoomGuard(domProps[n]);
        }
      }
      if (typeof domProps.onClick !== "function") {
        domProps.onClick = wrapOpenRoomGuard(null);
      }
    }
    try {
      item.setAttribute("data-jingepi-item-guard", "1");
    } catch (_eAttr) {
      /* ignore */
    }
  }

  /** 给更多/通知钮补 stopPropagation + 进房封锁；并加固父行 */
  function patchRoomListAuxButton(btn) {
    if (!btn) return;
    if (btn.classList && btn.classList.contains("mx_RoomListItemView")) return;
    var item = btn.closest(
      ".mx_RoomListItemView, .mx_RoomTile, [data-testid='room-list-item']"
    );
    if (!item || btn === item) return;

    var auxNames = [
      "onClick",
      "onPointerDown",
      "onPointerUp",
      "onMouseDown",
      "onMouseUp",
      "onTouchStart",
      "onTouchEnd",
    ];
    /* 每次重补 fiber（React 重渲染会换 memoizedProps） */
    patchFiberHandlers(getReactFiber(btn), auxNames, wrapAuxStopPropagation, 8);
    var props = getReactProps(btn);
    if (props) {
      for (var i = 0; i < auxNames.length; i++) {
        var name = auxNames[i];
        if (typeof props[name] === "function") {
          props[name] = wrapAuxStopPropagation(props[name]);
        }
      }
      /* 无 onClick 时也挂一个，挡住冒泡到父行 openRoom 的 click */
      if (typeof props.onClick !== "function" || !props.onClick.__jingepiAuxStop) {
        props.onClick = wrapAuxStopPropagation(
          typeof props.onClick === "function" ? props.onClick : null
        );
      }
      props.__jingepiStopWrapped = 1;
    }
    /* fiber 上也强制补 onClick 阻断 */
    try {
      var fiber = getReactFiber(btn);
      var f = fiber;
      for (var d = 0; d < 8 && f; d++) {
        var mp = f.memoizedProps || f.pendingProps;
        if (mp && (typeof mp.onClick !== "function" || !mp.onClick.__jingepiAuxStop)) {
          mp.onClick = wrapAuxStopPropagation(
            typeof mp.onClick === "function" ? mp.onClick : null
          );
          f.memoizedProps = mp;
        }
        f = f.return;
      }
    } catch (_eClick) {
      /* ignore */
    }

    patchRoomListItemOpenGuard(item);

    if (btn.getAttribute("data-jingepi-aux-native") === "1") return;
    btn.setAttribute("data-jingepi-aux-native", "1");
    function nativeArm(ev) {
      armBlockOpenRoom(500);
      /* capture 阶段勿 stopPropagation：会挡 Radix/React 菜单 */
      try {
        if (ev && ev.target) patchRoomListAuxButton(btn);
      } catch (_eArm) {
        /* ignore */
      }
    }
    ["pointerdown", "mousedown", "mouseup", "click", "touchstart", "touchend"].forEach(
      function (type) {
        btn.addEventListener(type, nativeArm, true);
      }
    );
  }

  function scanPatchRoomListAux(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var items = scope.querySelectorAll
      ? scope.querySelectorAll(
          ".mx_RoomListItemView, .mx_RoomTile, [data-testid='room-list-item']"
        )
      : [];
    for (var i = 0; i < items.length; i++) {
      patchRoomListItemOpenGuard(items[i]);
    }
    var nodes = scope.querySelectorAll
      ? scope.querySelectorAll(
          [
            ".mx_RoomListItemView [class*='_hoverMenu_'] button",
            ".mx_RoomListItemView button[aria-haspopup]",
            '.mx_RoomListItemView button[aria-label*="更多"]',
            '.mx_RoomListItemView button[aria-label*="More"]',
            '.mx_RoomListItemView button[aria-label*="通知"]',
            '.mx_RoomListItemView button[aria-label*="Notification"]',
            '.mx_RoomListItemView button[aria-label*="选项"]',
            '.mx_RoomListItemView button[aria-label*="Options"]',
            ".mx_RoomTile [class*='_hoverMenu_'] button",
            ".mx_RoomTile button[aria-haspopup]",
          ].join(", ")
        )
      : [];
    for (var j = 0; j < nodes.length; j++) {
      patchRoomListAuxButton(nodes[j]);
    }
  }

  function bindRoomListAuxGuards() {
    if (roomListAuxGuardBound) return;
    roomListAuxGuardBound = true;
    installHistoryNavGuard();

    function armIfChrome(ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      /*
       * Tab / 空间列表 chrome 不要 armBlockOpenRoom：
       * 选空间会 dispatch view_room(context_switch)，若仍在 suppress 窗内
       * 会被 revertBlockedRoomNavigation 打回 #/home，active space 变回「主页」。
       * 进房封锁只用于房间列表行内「更多/通知」。
       */
      if (
        t.closest(
          "#jingepi-mobile-tabbar, #jingepi-space-sheet, #jingepi-space-sheet-header, #jingepi-mobile-space-backdrop, #jingepi-mobile-back, #jingepi-left-panel-toggle, .mx_SpacePanel, .mx_SpaceButton, .mx_SpaceButton_menuButton, .mx_SpaceButton_toggleCollapse, .mx_SpacePanel_toggleCollapse"
        )
      ) {
        return;
      }
      if (isRoomNavChromeTarget(t)) {
        armBlockOpenRoom(500);
        try {
          var btn =
            t && t.closest
              ? t.closest(
                  ".mx_RoomListItemView [class*='_hoverMenu_'] button, .mx_RoomListItemView button[aria-haspopup], .mx_RoomTile button[aria-haspopup]"
                )
              : null;
          if (btn) patchRoomListAuxButton(btn);
          var item =
            t && t.closest
              ? t.closest(
                  ".mx_RoomListItemView, .mx_RoomTile, [data-testid='room-list-item']"
                )
              : null;
          if (item) patchRoomListItemOpenGuard(item);
        } catch (_ePatch) {
          /* ignore */
        }
        return;
      }
      /* 点房间名/整行进房：清除抑制（勿清 hoverMenu 误触） */
      if (t && t.closest && t.closest('[class*="_hoverMenu_"]')) return;
      if (t && t.closest && t.closest('[data-jingepi-aux-native="1"]')) return;
      var row =
        t && t.closest
          ? t.closest(
              ".mx_RoomListItemView, .mx_RoomTile, [data-testid='room-list-item'], a[href*='#/room/'], a[href*='#/user/']"
            )
          : null;
      if (row && !isBlockOpenRoomArmed()) {
        suppressRoomEnterUntil = 0;
      }
    }
    /* 仅标记抑制/重补 fiber；勿在 document 捕获期 stopPropagation（会挡菜单） */
    ["pointerdown", "mousedown", "touchstart", "click"].forEach(function (type) {
      document.addEventListener(type, armIfChrome, true);
    });

    window.addEventListener("hashchange", function () {
      if (mobileQqBackLock) return;
      if (isBlockOpenRoomArmed() || isSuppressRoomEnterArmed()) {
        if (revertBlockedRoomNavigation()) return;
      }
      /* 兼容旧路径：窄屏仍强制回列表 */
      if (!isSuppressRoomEnterArmed() && !isBlockOpenRoomArmed()) return;
      if (!isMobileViewport()) return;
      if (!isMobileChatRoute()) return;
      try {
        armMobileQqBackLock(900);
        document.body.setAttribute("data-jingepi-qq-list", "1");
        document.body.removeAttribute("data-jingepi-qq-chat");
        document.body.setAttribute("data-jingepi-mobile-roomlist", "1");
        document.body.removeAttribute("data-jingepi-chatting");
        mobileQqLastMode = "list";
        if ((location.hash || "") !== "#/home") {
          location.hash = "#/home";
        }
        setTimeout(function () {
          forceMobileListPanelGeometry();
          ensureMobileTabBar(true);
          syncMobileQqPages();
        }, 50);
      } catch (_eRev) {
        /* ignore */
      }
    });

    scanPatchRoomListAux(document);
    setInterval(function () {
      scanPatchRoomListAux(document);
    }, 2500);
    try {
      var auxObs = new MutationObserver(function (mutations) {
        for (var i = 0; i < mutations.length; i++) {
          var m = mutations[i];
          for (var j = 0; j < m.addedNodes.length; j++) {
            var n = m.addedNodes[j];
            if (!n || n.nodeType !== 1) continue;
            if (
              n.matches &&
              n.matches(
                '.mx_RoomListItemView, .mx_RoomTile, button[aria-haspopup], [class*="_hoverMenu_"]'
              )
            ) {
              scanPatchRoomListAux(n);
            } else if (n.querySelector) {
              scanPatchRoomListAux(n);
            }
          }
        }
      });
      auxObs.observe(document.documentElement, { childList: true, subtree: true });
    } catch (_eObs) {
      /* interval 已兜底 */
    }
  }

  function isMobileViewport() {
    try {
      return window.matchMedia("(max-width: 900px)").matches;
    } catch (_e) {
      return false;
    }
  }

  /** 桌面(>900) 离开窄屏时：清 QQ 标记、还 Space 窄栏、去掉手机 Tab/抽屉；幂等可反复调用 */
  function resetDesktopLayoutFromMobile() {
    if (!document.body) return;
    document.body.removeAttribute("data-jingepi-mobile");
    document.body.removeAttribute("data-jingepi-qq-list");
    document.body.removeAttribute("data-jingepi-qq-chat");
    document.body.removeAttribute("data-jingepi-mobile-roomlist");
    document.body.removeAttribute("data-jingepi-mobile-spaces");
    document.body.removeAttribute("data-jingepi-mobile-spacebar");
    document.body.removeAttribute("data-jingepi-chatting");

    /* 先收回展开、迁回 Space，再拆 sheet，避免桌面侧栏加宽或窄栏被删 */
    try {
      collapseSpacePanelAfterMobileList(
        document.querySelector("#jingepi-space-sheet > .mx_SpacePanel") ||
          document.querySelector(".mx_SpacePanel")
      );
      restoreSpacePanelHome();
    } catch (_eRest) {
      /* ignore */
    }
    var spaceInSheet =
      document.querySelector("#jingepi-space-sheet .mx_SpacePanel") ||
      document.querySelector(".mx_SpacePanel");
    var sheetNow = document.getElementById("jingepi-space-sheet");
    if (
      spaceInSheet &&
      sheetNow &&
      sheetNow.contains(spaceInSheet)
    ) {
      var left =
        document.querySelector(".mx_LeftPanel") ||
        document.querySelector(".mx_LeftPanel_wrapper");
      if (left) {
        try {
          left.insertBefore(spaceInSheet, left.firstChild);
        } catch (_eIns) {
          try {
            left.appendChild(spaceInSheet);
          } catch (_e2) {
            /* ignore */
          }
        }
      }
      mobileSpaceHomeParent = null;
      mobileSpaceHomeNext = null;
    }

    document.body.removeAttribute("data-jingepi-mobile-spaces");
    clearMobileListPanelGeometry();
    removeMobileBackButton();
    var tb = document.getElementById("jingepi-mobile-tabbar");
    if (tb) tb.remove();
    var bd = document.getElementById("jingepi-mobile-space-backdrop");
    if (bd) bd.remove();
    var sheet = document.getElementById("jingepi-space-sheet");
    if (sheet) {
      /* 二次确认：sheet 内不应再有 SpacePanel */
      var leftover = sheet.querySelector(".mx_SpacePanel");
      if (leftover) {
        var left2 =
          document.querySelector(".mx_LeftPanel") ||
          document.querySelector(".mx_LeftPanel_wrapper");
        if (left2) {
          try {
            left2.insertBefore(leftover, left2.firstChild);
          } catch (_e3) {
            /* ignore */
          }
        }
      }
      sheet.remove();
    }
    var toggle = document.getElementById("jingepi-left-panel-toggle");
    if (toggle && toggle.style) {
      toggle.style.removeProperty("display");
      toggle.style.removeProperty("visibility");
      toggle.style.removeProperty("opacity");
      toggle.style.removeProperty("pointer-events");
    }
    mobileQqLastMode = "";
  }

  function markMobileBodyFlag() {
    if (!document.body) return;
    if (isMobileViewport()) {
      document.body.setAttribute("data-jingepi-mobile", "1");
    } else {
      document.body.removeAttribute("data-jingepi-mobile");
    }
  }

  function isMobileChatRoute() {
    var h = location.hash || "";
    return /#\/(room|user)\//.test(h);
  }

  /** 选空间后的 context_switch：hash 在空间房，但仍应显示该空间下的频道列表 */
  function isViewingActiveSpaceAsRoom() {
    try {
      var ctx = window.mxSdkContext;
      var ss = ctx && (ctx._SpaceStore || ctx.spaceStore);
      var active = ss && ss.activeSpace;
      if (!active || active === "home-space" || active === "Home") return false;
      var h = location.hash || "";
      var m = h.match(/#\/room\/([^/?]+)/);
      if (!m) return false;
      var rid = decodeURIComponent(m[1]);
      return rid === active;
    } catch (_e) {
      return false;
    }
  }

  function removeMobileBackButton() {
    var btn = document.getElementById("jingepi-mobile-back");
    if (btn) btn.remove();
  }

  function armMobileQqBackLock(ms) {
    mobileQqBackLock = true;
    if (mobileQqBackLockTimer) clearTimeout(mobileQqBackLockTimer);
    mobileQqBackLockTimer = setTimeout(function () {
      mobileQqBackLock = false;
      mobileQqBackLockTimer = 0;
    }, ms || 900);
  }

  function goBackToChannelList() {
    if (!isMobileViewport()) return;
    if (mobileQqBackLock) return;
    armMobileQqBackLock(1000);
    /* 先切页态，避免随后 sync 因仍停在 #/room 又判回聊天 */
    document.body.setAttribute("data-jingepi-qq-list", "1");
    document.body.removeAttribute("data-jingepi-qq-chat");
    document.body.setAttribute("data-jingepi-mobile-roomlist", "1");
    document.body.removeAttribute("data-jingepi-chatting");
    closeMobileSpaceSheet();
    removeMobileBackButton();
    mobileQqLastMode = "list";
    var needHashHome = false;
    try {
      if (isMobileChatRoute()) {
        needHashHome = true;
        /* 只改 hash，勿再点 Home（避免双路由 / iframe 里 history 锁死） */
        if ((location.hash || "") !== "#/home") {
          location.hash = "#/home";
        }
      }
    } catch (_eHash) {
      /* ignore */
    }
    var sep = findLeftPanelSeparator();
    if (sep) {
      expandLeftPanelViaSeparator(sep);
    } else {
      setRoomListCollapsedFlag(false);
      releaseCollapsedRoomListStyles();
      nudgeRoomListLayout();
    }
    /* hash 已切 home 时不必再 fireDomClick(Home)，否则易与 hashchange/observer 互撞 */
    if (!needHashHome) {
      try {
        var homeBtn =
          document.querySelector(".mx_SpacePanel .mx_SpaceButton_home") ||
          document.querySelector(".mx_SpacePanel [aria-label*='主页']") ||
          document.querySelector(".mx_SpacePanel [aria-label*='Home']") ||
          document.querySelector(".mx_SpacePanel [aria-label*='home']");
        if (homeBtn) fireDomClick(homeBtn);
      } catch (_e0) {
        /* ignore */
      }
    }
    ensureMobileTabBar(true);
    syncMobileSpaceBar();
    forceMobileListPanelGeometry();
    setTimeout(function () {
      if (!mobileQqBackLock) syncMobileQqPages();
      else {
        /* 锁内只做轻量同步，禁止再展开/改 hash */
        forceMobileListPanelGeometry();
        ensureMobileTabBar(true);
      }
    }, 200);
    setTimeout(function () {
      syncMobileQqPages();
    }, 1100);
  }

  function ensureMobileBackButton() {
    if (!isMobileViewport() || !isMobileChatRoute()) {
      removeMobileBackButton();
      return;
    }
    var header = findCurrentRoomHeader();
    if (!header) return;
    var btn = document.getElementById("jingepi-mobile-back");
    if (btn && !header.contains(btn)) {
      btn.remove();
      btn = null;
    }
    if (!btn) {
      btn = document.createElement("button");
      btn.id = "jingepi-mobile-back";
      btn.type = "button";
      btn.className = "jingepi-mobile-back";
      btn.setAttribute("aria-label", "返回频道列表");
      btn.setAttribute("title", "返回");
      btn.innerHTML =
        '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">' +
        '<path fill="currentColor" d="M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z"/>' +
        "</svg>";
      function stopBackBubble(ev) {
        try {
          ev.stopPropagation();
        } catch (_eStop) {
          /* ignore */
        }
      }
      btn.addEventListener("pointerdown", stopBackBubble, true);
      btn.addEventListener("mousedown", stopBackBubble, true);
      btn.addEventListener("click", function (ev) {
        try {
          ev.preventDefault();
        } catch (_ePrev) {
          /* ignore */
        }
        stopBackBubble(ev);
        goBackToChannelList();
      });
    }
    if (header.firstElementChild !== btn) {
      header.insertBefore(btn, header.firstChild);
    }
  }

  function openUserSettingsFromTab() {
    var qs =
      document.querySelector(".mx_QuickSettingsButton button") ||
      document.querySelector(".mx_QuickSettingsButton .mx_AccessibleButton") ||
      document.querySelector(".mx_QuickSettingsButton");
    if (qs) {
      fireDomClick(qs);
      return;
    }
    var menuBtn =
      document.querySelector(".mx_UserMenu button") ||
      document.querySelector(".mx_UserMenu .mx_AccessibleButton");
    if (!menuBtn) return;
    fireDomClick(menuBtn);
    setTimeout(function () {
      var items = document.querySelectorAll(
        '[role="menuitem"], .mx_IconizedContextMenu_item, .mx_AccessibleButton'
      );
      for (var i = 0; i < items.length; i++) {
        var t = (items[i].textContent || "").replace(/\s+/g, " ").trim();
        if (/全部设置|All settings|^设置$|^Settings$/i.test(t)) {
          fireDomClick(items[i]);
          return;
        }
      }
    }, 120);
  }

  function openUserMenuFromTab() {
    var menuBtn =
      document.querySelector(".mx_UserMenu button") ||
      document.querySelector(".mx_UserMenu .mx_AccessibleButton") ||
      document.querySelector(".mx_UserMenu");
    if (menuBtn) fireDomClick(menuBtn);
  }

  /* Space 列表页：遮罩与面板同挂 body 级 sheet；打开时展开窄栏以显示名称 */
  var mobileSpaceHomeParent = null;
  var mobileSpaceHomeNext = null;
  var mobileSpaceExpandedByUs = false;
  var mobileSpaceExpandRequested = false;

  function expandSpacePanelForMobileList(space) {
    if (!space || !isMobileViewport()) return;
    var needsExpand =
      space.classList.contains("collapsed") ||
      !!space.querySelector(".mx_SpaceButton_narrow");
    if (!needsExpand) return;
    /* 已点过展开：勿再点，否则会 toggle 回窄栏 */
    if (mobileSpaceExpandRequested) return;
    var toggle = space.querySelector(".mx_SpacePanel_toggleCollapse");
    if (!toggle) return;
    mobileSpaceExpandRequested = true;
    mobileSpaceExpandedByUs = true;
    try {
      fireDomClick(toggle);
    } catch (_e) {
      mobileSpaceExpandRequested = false;
    }
  }

  function collapseSpacePanelAfterMobileList(space) {
    mobileSpaceExpandRequested = false;
    if (!mobileSpaceExpandedByUs) return;
    mobileSpaceExpandedByUs = false;
    space =
      space ||
      document.querySelector("#jingepi-space-sheet > .mx_SpacePanel") ||
      document.querySelector(".mx_SpacePanel");
    if (!space) return;
    if (space.classList.contains("collapsed")) return;
    var toggle = space.querySelector(".mx_SpacePanel_toggleCollapse");
    if (!toggle) return;
    try {
      fireDomClick(toggle);
    } catch (_e) {
      /* ignore */
    }
  }

  function restoreSpacePanelHome() {
    var space =
      document.querySelector("#jingepi-space-sheet > .mx_SpacePanel") ||
      document.querySelector(".mx_SpacePanel");
    if (!space || !mobileSpaceHomeParent || !document.contains(mobileSpaceHomeParent)) {
      mobileSpaceHomeParent = null;
      mobileSpaceHomeNext = null;
      return;
    }
    if (space.parentElement === mobileSpaceHomeParent) {
      mobileSpaceHomeParent = null;
      mobileSpaceHomeNext = null;
      return;
    }
    try {
      if (mobileSpaceHomeNext && mobileSpaceHomeNext.parentNode === mobileSpaceHomeParent) {
        mobileSpaceHomeParent.insertBefore(space, mobileSpaceHomeNext);
      } else {
        mobileSpaceHomeParent.appendChild(space);
      }
    } catch (_e) {
      try {
        mobileSpaceHomeParent.appendChild(space);
      } catch (_e2) {
        /* ignore */
      }
    }
    mobileSpaceHomeParent = null;
    mobileSpaceHomeNext = null;
  }

  function getElementReactRoot() {
    return (
      document.getElementById("matrixchat") ||
      document.getElementById("root") ||
      document.querySelector("#matrixchat, #root, .mx_MatrixChat") ||
      document.body ||
      document.documentElement
    );
  }

  function ensureSpaceSheet() {
    var sheet = document.getElementById("jingepi-space-sheet");
    var host = getElementReactRoot();
    if (!sheet) {
      sheet = document.createElement("div");
      sheet.id = "jingepi-space-sheet";
      sheet.setAttribute("role", "dialog");
      sheet.setAttribute("aria-label", "空间列表");
      /* 挂在 React 根内，避免与 Element 事件委托脱节 */
      host.appendChild(sheet);
    } else if (host && sheet.parentElement !== host) {
      try {
        host.appendChild(sheet);
      } catch (_eHost) {
        /* ignore */
      }
    }
    var bd = document.getElementById("jingepi-mobile-space-backdrop");
    if (!bd) {
      bd = document.createElement("button");
      bd.id = "jingepi-mobile-space-backdrop";
      bd.type = "button";
      bd.setAttribute("aria-label", "关闭空间列表");
      bd.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        closeMobileSpaceSheet();
      });
    }
    var hdr = document.getElementById("jingepi-space-sheet-header");
    if (!hdr) {
      hdr = document.createElement("div");
      hdr.id = "jingepi-space-sheet-header";
      hdr.innerHTML =
        '<button type="button" id="jingepi-space-sheet-back" class="jingepi-space-sheet-back" aria-label="返回频道">' +
        '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">' +
        '<path fill="currentColor" d="M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z"/>' +
        "</svg></button>" +
        '<div class="jingepi-space-sheet-title">空间</div>' +
        '<span class="jingepi-space-sheet-spacer" aria-hidden="true"></span>';
      var backBtn = hdr.querySelector("#jingepi-space-sheet-back");
      if (backBtn) {
        backBtn.addEventListener("click", function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          closeMobileSpaceSheet();
        });
      }
    }
    if (bd.parentElement !== sheet || sheet.firstElementChild !== bd) {
      sheet.insertBefore(bd, sheet.firstChild);
    }
    if (hdr.parentElement !== sheet) {
      sheet.insertBefore(hdr, bd.nextSibling);
    } else if (hdr.previousElementSibling !== bd) {
      sheet.insertBefore(hdr, bd.nextSibling);
    }
    /* 勿把 SpacePanel 挪进 sheet：移出原树会丢 React 委托，选空间/更多失效 */
    var stuck = sheet.querySelector(".mx_SpacePanel");
    if (stuck) {
      restoreSpacePanelHome();
    }
    return sheet;
  }

  /** 保留 SpacePanel 在 React 原位；仅展开窄栏并返回节点 */
  function mountSpacePanelInSheet(sheet) {
    var space = document.querySelector(".mx_SpacePanel");
    if (!space) return null;
    /* 若历史版本已把面板塞进 sheet，先迁回 */
    if (sheet && space.parentElement === sheet) {
      restoreSpacePanelHome();
      space = document.querySelector(".mx_SpacePanel");
    }
    return space;
  }

  function isSpaceSheetAuxClickTarget(t) {
    if (!t || !t.closest) return false;
    return !!(
      t.closest(".mx_SpaceButton_menuButton") ||
      t.closest(".mx_SpaceButton_toggleCollapse") ||
      t.closest(".mx_SpacePanel_toggleCollapse") ||
      t.closest(".mx_SpacePanel_contextMenu") ||
      t.closest(
        '[role="menu"], [data-radix-menu-content], .mx_IconizedContextMenu, .mx_ContextualMenu, .mx_Dialog'
      )
    );
  }

  /**
   * 空间列表：点 Space 行主体（原生 SpaceButton click）选中后关列表回频道；
   * 点「更多」只开 Element 菜单，不关 sheet、不抢选空间。
   */
  function bindSpaceSheetAutoClose(space) {
    if (!space || space.getAttribute("data-jingepi-space-sheet-bound") === "1") return;
    space.setAttribute("data-jingepi-space-sheet-bound", "1");
    space.addEventListener(
      "click",
      function (ev) {
        if (!document.body || document.body.getAttribute("data-jingepi-mobile-spaces") !== "1") {
          return;
        }
        var t = ev.target;
        if (!t || !t.closest) return;
        if (isSpaceSheetAuxClickTarget(t)) return;
        var btn = t.closest(".mx_SpaceButton, .mx_SpaceButton_home");
        if (!btn || !space.contains(btn)) return;
        /* 勿把「更多」误当成行主体（menuButton 在 SpaceButton 内） */
        if (t.closest(".mx_SpaceButton_menuButton")) return;
        /* 标准 click 已落到原生 Space 项；稍候关列表回频道 */
        setTimeout(function () {
          if (
            !document.body ||
            document.body.getAttribute("data-jingepi-mobile-spaces") !== "1"
          ) {
            return;
          }
          if (
            document.querySelector(
              '.mx_SpacePanel_contextMenu, .mx_IconizedContextMenu, .mx_ContextualMenu, [role="menu"]'
            )
          ) {
            return;
          }
          closeMobileSpaceSheet();
          if (!isMobileViewport() || !document.body) return;
          try {
            armMobileQqBackLock(900);
            document.body.setAttribute("data-jingepi-qq-list", "1");
            document.body.removeAttribute("data-jingepi-qq-chat");
            document.body.setAttribute("data-jingepi-mobile-roomlist", "1");
            document.body.removeAttribute("data-jingepi-chatting");
            mobileQqLastMode = "list";
            forceMobileListPanelGeometry();
            ensureMobileTabBar(true);
            syncMobileQqPages();
          } catch (_eAfter) {
            /* ignore */
          }
        }, 280);
      },
      false
    );
  }

  function closeMobileSpaceSheet() {
    if (!document.body) return;
    document.body.removeAttribute("data-jingepi-mobile-spaces");
    var spaceNow = document.querySelector(".mx_SpacePanel");
    /* 先收回展开，避免桌面侧栏被永久加宽；面板始终留在 React 原位 */
    collapseSpacePanelAfterMobileList(spaceNow);
    restoreSpacePanelHome();
    var sheet = document.getElementById("jingepi-space-sheet");
    if (sheet) {
      var stuck = sheet.querySelector(".mx_SpacePanel");
      if (stuck) {
        var left =
          document.querySelector(".mx_LeftPanel") ||
          document.querySelector(".mx_LeftPanel_wrapper");
        if (left) {
          try {
            left.insertBefore(stuck, left.firstChild);
          } catch (_e) {
            try {
              left.appendChild(stuck);
            } catch (_e2) {
              /* ignore */
            }
          }
        }
        mobileSpaceHomeParent = null;
        mobileSpaceHomeNext = null;
      }
      sheet.remove();
    }
    var bd = document.getElementById("jingepi-mobile-space-backdrop");
    if (bd) bd.remove();
    var bar = document.getElementById("jingepi-mobile-tabbar");
    if (bar) {
      var sp = bar.querySelector('[data-jingepi-tab="spaces"]');
      if (sp) sp.removeAttribute("aria-current");
      var ch = bar.querySelector('[data-jingepi-tab="channels"]');
      if (ch && document.body.getAttribute("data-jingepi-qq-list") === "1") {
        ch.setAttribute("aria-current", "page");
      }
    }
  }

  function openMobileSpaceSheet() {
    if (!isMobileViewport() || !document.body) return;
    /* 仅列表页打开；勿动侧栏 expand/collapse，避免 crush */
    if (document.body.getAttribute("data-jingepi-qq-chat") === "1") return;
    document.body.setAttribute("data-jingepi-qq-list", "1");
    document.body.setAttribute("data-jingepi-mobile-roomlist", "1");
    clearSpacePanelHideInline();
    var sheet = ensureSpaceSheet();
    var space = mountSpacePanelInSheet(sheet);
    /* 先展开窄栏（toggle 尚未被列表 CSS 隐藏），再显列表页 */
    expandSpacePanelForMobileList(space);
    document.body.setAttribute("data-jingepi-mobile-spaces", "1");
    bindSpaceSheetAutoClose(space);
    /* React 重绘后若仍窄栏则再试一次展开（面板不挪入 sheet） */
    setTimeout(function () {
      if (!document.body || document.body.getAttribute("data-jingepi-mobile-spaces") !== "1") {
        return;
      }
      var sp2 = document.querySelector(".mx_SpacePanel");
      if (
        sp2 &&
        (sp2.classList.contains("collapsed") ||
          sp2.querySelector(".mx_SpaceButton_narrow"))
      ) {
        mobileSpaceExpandRequested = false;
        expandSpacePanelForMobileList(sp2);
      }
      bindSpaceSheetAutoClose(sp2);
    }, 200);
    var bar = document.getElementById("jingepi-mobile-tabbar");
    if (bar) {
      var tabs = bar.querySelectorAll("[data-jingepi-tab]");
      for (var i = 0; i < tabs.length; i++) {
        tabs[i].removeAttribute("aria-current");
      }
      var sp = bar.querySelector('[data-jingepi-tab="spaces"]');
      if (sp) sp.setAttribute("aria-current", "page");
    }
  }

  /** 列表页：把 Tab 条插到搜索框正上方（非屏幕底栏） */
  function placeMobileTabBarAboveSearch(bar) {
    if (!bar) return;
    var panel =
      document.querySelector(".mx_RoomListPanel") ||
      document.querySelector(".mx_LeftPanel_roomListContainer") ||
      document.querySelector(".mx_LeftPanel_wrapperPanel");
    var search =
      document.querySelector(".mx_RoomListSearch") ||
      document.querySelector('[class*="RoomListSearch"]') ||
      document.querySelector(".mx_RoomListHeader");
    /* 新版 Compound 房间列表：搜索在 panel 直系子级 [class*=_view_] 内 */
    if (!search && panel) {
      var view = panel.querySelector(':scope > [class*="_view_"]');
      if (view && view.querySelector('[class*="_search_"]')) {
        search = view;
      } else {
        var searchHit =
          panel.querySelector('button[class*="_search_"]') ||
          panel.querySelector('[class*="_search_container_"]') ||
          panel.querySelector('[class*="_search_"]');
        if (searchHit) {
          search = searchHit;
          while (
            search.parentElement &&
            search.parentElement !== panel &&
            search.parentElement !== document.body
          ) {
            search = search.parentElement;
          }
        }
      }
    }
    if (search && search.parentNode) {
      if (bar.nextElementSibling !== search) {
        search.parentNode.insertBefore(bar, search);
      }
      return;
    }
    if (panel) {
      if (bar.parentNode !== panel || panel.firstElementChild !== bar) {
        panel.insertBefore(bar, panel.firstChild);
      }
      return;
    }
    var left = document.querySelector(".mx_LeftPanel");
    if (left) {
      if (bar.parentNode !== left || left.firstElementChild !== bar) {
        left.insertBefore(bar, left.firstChild);
      }
      return;
    }
    if (!bar.parentNode) {
      (document.body || document.documentElement).appendChild(bar);
    }
  }

  function ensureMobileTabBar(show) {
    var bar = document.getElementById("jingepi-mobile-tabbar");
    if (!isMobileViewport()) {
      if (bar) bar.remove();
      /* 桌面：完整复位，勿只 close sheet（避免漏清 QQ 标记） */
      resetDesktopLayoutFromMobile();
      return;
    }
    if (!show) {
      if (bar) {
        bar.setAttribute("data-open", "0");
        bar.style.display = "none";
      }
      closeMobileSpaceSheet();
      return;
    }
    if (
      bar &&
      (!bar.querySelector('[data-jingepi-tab="spaces"]') ||
        bar.querySelector('[data-jingepi-tab="settings"]'))
    ) {
      /* 旧版无「空间」或仍有独立「设置」：整栏重建 */
      bar.remove();
      bar = null;
    }
    if (!bar) {
      bar = document.createElement("nav");
      bar.id = "jingepi-mobile-tabbar";
      bar.setAttribute("aria-label", "频道导航");
      bar.innerHTML =
        '<button type="button" class="jingepi-mobile-tab" data-jingepi-tab="channels" aria-label="频道">' +
        '<span class="jingepi-tab-ico" aria-hidden="true">' +
        '<svg viewBox="0 0 24 24" width="22" height="22"><path fill="currentColor" d="M4 6h16v2H4V6zm0 5h16v2H4v-2zm0 5h10v2H4v-2z"/></svg>' +
        "</span><span class=\"jingepi-tab-label\">频道</span></button>" +
        '<button type="button" class="jingepi-mobile-tab" data-jingepi-tab="spaces" aria-label="空间">' +
        '<span class="jingepi-tab-ico" aria-hidden="true">' +
        '<svg viewBox="0 0 24 24" width="22" height="22"><path fill="currentColor" d="M12 2 2 7l10 5 10-5-10-5zm0 9.25L4.5 7.5 12 3.75 19.5 7.5 12 11.25zM2 17l10 5 10-5-2.1-1.05L12 19.5l-7.9-3.55L2 17zm0-4.5 10 5 10-5-2.1-1.05L12 15l-7.9-3.55L2 12.5z"/></svg>' +
        "</span><span class=\"jingepi-tab-label\">空间</span></button>" +
        '<button type="button" class="jingepi-mobile-tab" data-jingepi-tab="me" aria-label="我的">' +
        '<span class="jingepi-tab-ico jingepi-tab-avatar" aria-hidden="true">我</span>' +
        '<span class="jingepi-tab-label">我的</span></button>';
      function stopTabBubble(ev) {
        var tab =
          ev.target && ev.target.closest
            ? ev.target.closest("[data-jingepi-tab]")
            : null;
        if (!tab || !bar.contains(tab)) return;
        try {
          ev.stopPropagation();
        } catch (_eStop) {
          /* ignore */
        }
      }
      bar.addEventListener("pointerdown", stopTabBubble, true);
      bar.addEventListener("mousedown", stopTabBubble, true);
      /* Tab 导航只用 click，不用 pointerdown 切换页态 */
      bar.addEventListener("click", function (ev) {
        var tab =
          ev.target && ev.target.closest
            ? ev.target.closest("[data-jingepi-tab]")
            : null;
        if (!tab || !bar.contains(tab)) return;
        try {
          ev.preventDefault();
        } catch (_ePrev) {
          /* ignore */
        }
        stopTabBubble(ev);
        var key = tab.getAttribute("data-jingepi-tab");
        if (key === "channels") {
          closeMobileSpaceSheet();
          goBackToChannelList();
        } else if (key === "spaces") {
          if (document.body.getAttribute("data-jingepi-mobile-spaces") === "1") {
            closeMobileSpaceSheet();
          } else {
            openMobileSpaceSheet();
          }
        } else if (key === "me") {
          closeMobileSpaceSheet();
          openUserMenuFromTab();
        }
      });
    }
    /* 每次显示都重新挂到搜索上方，应对 React 重绘把节点冲掉 */
    placeMobileTabBarAboveSearch(bar);
    /* 同步头像缩略（有则替换「我」字）；同源不重建，避免 MutationObserver 死循环 */
    try {
      var av =
        document.querySelector(".mx_UserMenu .mx_BaseAvatar_image") ||
        document.querySelector(".mx_UserMenu img") ||
        document.querySelector(".mx_UserMenu .mx_BaseAvatar");
      var slot = bar.querySelector(".jingepi-tab-avatar");
      if (slot && av) {
        if (av.tagName === "IMG" && av.src) {
          var existingImg = slot.querySelector("img");
          if (
            !(existingImg && existingImg.getAttribute("src") === av.src)
          ) {
            slot.textContent = "";
            var img = document.createElement("img");
            img.src = av.src;
            img.alt = "";
            slot.appendChild(img);
          }
        } else {
          var letter = (av.textContent || "我").replace(/\s+/g, "").slice(0, 1);
          if (letter && slot.textContent !== letter) slot.textContent = letter;
        }
      }
    } catch (_e2) {
      /* ignore */
    }
    if (bar.getAttribute("data-open") !== "1") {
      bar.setAttribute("data-open", "1");
    }
    if (bar.style.display !== "flex") {
      bar.style.display = "flex";
    }
    if (document.body.getAttribute("data-jingepi-mobile-spaces") === "1") {
      var sheetKeep = ensureSpaceSheet();
      bindSpaceSheetAutoClose(mountSpacePanelInSheet(sheetKeep));
    } else {
      var ch = bar.querySelector('[data-jingepi-tab="channels"]');
      if (ch && ch.getAttribute("aria-current") !== "page") {
        ch.setAttribute("aria-current", "page");
      }
    }
  }

  function clearMobileListPanelGeometry() {
    var marked = document.querySelectorAll("[data-jingepi-qq-list-panel='1']");
    for (var i = 0; i < marked.length; i++) {
      var el = marked[i];
      if (!el || !el.style) continue;
      el.style.removeProperty("position");
      el.style.removeProperty("left");
      el.style.removeProperty("top");
      el.style.removeProperty("right");
      el.style.removeProperty("bottom");
      el.style.removeProperty("width");
      el.style.removeProperty("max-width");
      el.style.removeProperty("min-width");
      el.style.removeProperty("height");
      el.style.removeProperty("transform");
      el.style.removeProperty("opacity");
      el.style.removeProperty("visibility");
      el.style.removeProperty("z-index");
      el.style.removeProperty("pointer-events");
      el.removeAttribute("data-jingepi-qq-list-panel");
    }
  }

  /** 列表页：强制 LeftPanel 贴满视口（折叠动画 / spotlight 会把列甩到负 x） */
  function forceMobileListPanelGeometry() {
    if (!isMobileViewport()) return;
    if (document.body.getAttribute("data-jingepi-qq-list") !== "1") return;
    var nodes = document.querySelectorAll(
      ".mx_LeftPanel, .mx_LeftPanel_wrapper"
    );
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (!el || !el.style) continue;
      el.setAttribute("data-jingepi-qq-list-panel", "1");
      el.style.setProperty("position", "fixed", "important");
      el.style.setProperty("left", "0px", "important");
      el.style.setProperty("top", "0px", "important");
      el.style.setProperty("right", "0px", "important");
      el.style.setProperty("bottom", "0px", "important");
      el.style.setProperty("width", "100vw", "important");
      el.style.setProperty("max-width", "100vw", "important");
      el.style.setProperty("min-width", "100%", "important");
      el.style.setProperty("height", "100%", "important");
      el.style.setProperty("transform", "none", "important");
      el.style.setProperty("opacity", "1", "important");
      el.style.setProperty("visibility", "visible", "important");
      el.style.setProperty("z-index", "50", "important");
      el.style.setProperty("pointer-events", "auto", "important");
    }
  }

  function dismissMobileSpotlight() {
    if (!isMobileViewport()) return;
    var buttons = document.querySelectorAll(
      "button, .mx_AccessibleButton, [role='button']"
    );
    for (var i = 0; i < buttons.length; i++) {
      var t = (buttons[i].textContent || "").replace(/\s+/g, " ").trim();
      if (!/^(确定|知道了|Got it|OK)$/i.test(t)) continue;
      var host =
        buttons[i].closest(
          ".mx_Toast_toast, .mx_ToastContainer, [class*='Tooltip'], [class*='spotlight'], [class*='Spotlight'], [class*='Tour'], [role='dialog']"
        ) || buttons[i].parentElement;
      var blob = ((host && host.textContent) || "").replace(/\s+/g, " ");
      if (!/区域|分组聊天|Areas?|well organised|well organized/i.test(blob)) {
        continue;
      }
      try {
        fireDomClick(buttons[i]);
      } catch (_e) {
        /* ignore */
      }
      return;
    }
  }

  /**
   * 窄屏 QQ 页态：列表全屏 / 聊天全屏互斥。
   * 返回键展开列表并 hash→home；进房则收起列表。勿 crush 列表宽。
   */
  function syncMobileQqPages() {
    if (!document.body) return;
    markMobileBodyFlag();
    if (!isMobileViewport()) {
      /* 无论上次是否进过 QQ 态，桌面都必须复位（resize 可能先清了 lastMode） */
      resetDesktopLayoutFromMobile();
      return;
    }

    /* 以路由为准：#/room|/user → 聊天页；返回时 hash 已切 #/home */
    var wantChat = isMobileChatRoute();
    /* 刚选中空间时 hash 会到空间房本身：仍留在列表，展示该空间下频道 */
    if (wantChat && isViewingActiveSpaceAsRoom()) {
      wantChat = false;
    }
    /* 返回锁 / 更多·通知封锁期间强制列表态，禁止因短暂残留 #/room 又切回聊天 */
    if (mobileQqBackLock || isBlockOpenRoomArmed() || isSuppressRoomEnterArmed()) {
      wantChat = false;
    }
    var mode = wantChat ? "chat" : "list";

    /* 同态且非返回首帧：只做轻量几何/按钮同步，避免反复 expand/collapse */
    if (mode === mobileQqLastMode && !mobileQqBackLock) {
      if (mode === "chat") {
        ensureMobileBackButton();
        ensureMobileTabBar(false);
      } else {
        ensureMobileTabBar(true);
        forceMobileListPanelGeometry();
      }
      return;
    }

    if (mode === "chat") {
      document.body.setAttribute("data-jingepi-qq-chat", "1");
      document.body.removeAttribute("data-jingepi-qq-list");
      document.body.setAttribute("data-jingepi-chatting", "1");
      document.body.removeAttribute("data-jingepi-mobile-roomlist");
      closeMobileSpaceSheet();
      clearMobileListPanelGeometry();
      ensureMobileBackButton();
      ensureMobileTabBar(false);
      if (mobileQqLastMode !== "chat") {
        var sep = findLeftPanelSeparator();
        if (sep && !isRoomListCollapsedUi(sep) && !leftPanelExpanding) {
          collapseLeftPanelViaSeparator(sep);
        } else if (!sep) {
          setRoomListCollapsedFlag(true);
        }
      }
    } else {
      document.body.setAttribute("data-jingepi-qq-list", "1");
      document.body.removeAttribute("data-jingepi-qq-chat");
      document.body.setAttribute("data-jingepi-mobile-roomlist", "1");
      document.body.removeAttribute("data-jingepi-chatting");
      removeMobileBackButton();
      ensureMobileTabBar(true);
      clearSpacePanelHideInline();
      if (!mobileQqBackLock) dismissMobileSpotlight();
      var needExpand =
        !mobileQqBackLock &&
        (mobileQqLastMode !== "list" ||
          document.body.getAttribute("data-jingepi-roomlist-collapsed") === "1");
      if (needExpand && !leftPanelExpanding) {
        var sep2 = findLeftPanelSeparator();
        if (sep2 && isRoomListCollapsedUi(sep2)) {
          expandLeftPanelViaSeparator(sep2);
        } else {
          setRoomListCollapsedFlag(false);
          releaseCollapsedRoomListStyles();
          nudgeRoomListLayout();
        }
      }
      forceMobileListPanelGeometry();
    }
    mobileQqLastMode = mode;
  }

  function bindMobileQqNav() {
    bindRoomListAuxGuards();
    if (!mobileQqHashBound) {
      mobileQqHashBound = true;
      window.addEventListener("hashchange", function () {
        /* 返回过程中勿重置 mode / 勿抢 hash，避免与 goBack 互踢 */
        if (mobileQqBackLock) {
          forceMobileListPanelGeometry();
          ensureMobileTabBar(true);
          return;
        }
        /* 桌面路径 sync 内会 reset；窄屏同态轻量同步 */
        syncMobileQqPages();
        setTimeout(function () {
          if (!mobileQqBackLock) syncMobileQqPages();
        }, 200);
      });
    }
    if (!mobileQqListClickBound) {
      mobileQqListClickBound = true;
      /* 只用 click（按下+抬起），不用 pointerdown/touchstart 进房 */
      document.addEventListener(
        "click",
        function (ev) {
          if (!isMobileViewport()) return;
          var t = ev.target;
          if (!t || !t.closest) return;
          /* 更多/通知/菜单/Tab 等：绝不切聊天页 */
          if (isRoomNavChromeTarget(t)) return;
          if (isSuppressRoomEnterArmed() || isBlockOpenRoomArmed()) return;
          var item = t.closest(
            ".mx_RoomListItemView, .mx_RoomTile, [data-testid='room-list-item'], a[href*='#/room/'], a[href*='#/user/']"
          );
          if (!item) return;
          /* 点进房间后稍候切聊天页（等 hash / RoomHeader 就绪） */
          setTimeout(function () {
            if (!isMobileViewport()) return;
            if (
              isSuppressRoomEnterArmed() ||
              isBlockOpenRoomArmed() ||
              mobileQqBackLock
            ) {
              return;
            }
            mobileQqLastMode = "";
            syncMobileQqPages();
          }, 80);
          setTimeout(function () {
            if (
              !isMobileViewport() ||
              isSuppressRoomEnterArmed() ||
              isBlockOpenRoomArmed() ||
              mobileQqBackLock
            ) {
              return;
            }
            syncMobileQqPages();
          }, 280);
        },
        true
      );
    }
  }

  /**
   * 窄屏：按 QQ 页态 / 真实布局同步底栏显隐。
   * 列表页 → 自定义 Tab；聊天页 → 全藏，避免挡发送栏。
   */
  function syncMobileSpaceBar() {
    if (!document.body) return;
    markMobileBodyFlag();
    var mobile = isMobileViewport();
    if (!mobile) {
      resetDesktopLayoutFromMobile();
      return;
    }
    /* QQ 页态优先 */
    if (document.body.getAttribute("data-jingepi-qq-chat") === "1") {
      document.body.removeAttribute("data-jingepi-mobile-roomlist");
      document.body.setAttribute("data-jingepi-chatting", "1");
      ensureMobileTabBar(false);
      return;
    }
    if (document.body.getAttribute("data-jingepi-qq-list") === "1") {
      document.body.setAttribute("data-jingepi-mobile-roomlist", "1");
      document.body.removeAttribute("data-jingepi-chatting");
      clearSpacePanelHideInline();
      ensureMobileTabBar(true);
      return;
    }
    var expanding = document.body.classList.contains("jingepi-panel-expanding");
    var collapsedFlag =
      document.body.getAttribute("data-jingepi-roomlist-collapsed") === "1";
    var list =
      document.querySelector(".mx_RoomListPanel") ||
      document.querySelector(".mx_LeftPanel_wrapperPanel") ||
      document.querySelector("[data-testid='room-list']") ||
      document.querySelector(".mx_LeftPanel");
    var room = document.querySelector(".mx_RoomView");
    var vw = Math.max(window.innerWidth || 0, 1);
    var listW = 0;
    var roomW = 0;
    if (list) {
      var lr = list.getBoundingClientRect();
      if (lr.width > 0 && lr.height > 80) listW = lr.width;
    }
    if (room) {
      var rr = room.getBoundingClientRect();
      if (rr.width > 0 && rr.height > 80) roomW = rr.width;
    }
    var showingList =
      expanding ||
      listW >= vw * 0.55 ||
      (listW > 160 && roomW < vw * 0.35) ||
      (!collapsedFlag && listW > 120 && listW >= roomW);
    if (showingList) {
      document.body.setAttribute("data-jingepi-mobile-roomlist", "1");
      document.body.removeAttribute("data-jingepi-chatting");
      clearSpacePanelHideInline();
      ensureMobileTabBar(true);
    } else {
      document.body.removeAttribute("data-jingepi-mobile-roomlist");
      document.body.setAttribute("data-jingepi-chatting", "1");
      ensureMobileTabBar(false);
    }
  }

  function releaseCollapsedRoomListStyles() {
    var marked = document.querySelectorAll("[data-jingepi-collapsed-col]");
    for (var i = 0; i < marked.length; i++) {
      clearCollapsedColStyles(marked[i]);
    }
    clearSpacePanelHideInline();
    syncMobileSpaceBar();
  }

  function beginLeftPanelExpanding() {
    leftPanelExpanding = true;
    disarmUserCollapse();
    setRoomListCollapsedFlag(false);
    if (document.body) {
      document.body.classList.add("jingepi-panel-expanding");
    }
    releaseCollapsedRoomListStyles();
    nudgeRoomListLayout();
    if (leftPanelExpandTimer) clearTimeout(leftPanelExpandTimer);
    leftPanelExpandTimer = setTimeout(function () {
      endLeftPanelExpanding();
      enhanceLeftPanelToggle();
    }, 800);
  }

  /** 清掉 width:0 / flex:0 后，催 Element 虚拟列表重新量高 */
  function nudgeRoomListLayout() {
    try {
      window.dispatchEvent(new Event("resize"));
    } catch (_e0) {
      /* ignore */
    }
    try {
      var list =
        document.querySelector("[data-testid='room-list']") ||
        document.querySelector(".mx_RoomList") ||
        document.querySelector(".mx_RoomListPanel");
      if (list) {
        void list.offsetHeight;
        if (list.style) {
          list.style.removeProperty("height");
          list.style.removeProperty("min-height");
          list.style.removeProperty("max-height");
        }
      }
    } catch (_e1) {
      /* ignore */
    }
  }

  function endLeftPanelExpanding() {
    leftPanelExpanding = false;
    if (document.body) {
      document.body.classList.remove("jingepi-panel-expanding");
    }
    if (leftPanelExpandTimer) {
      clearTimeout(leftPanelExpandTimer);
      leftPanelExpandTimer = 0;
    }
  }

  function getReactFiber(dom) {
    if (!dom) return null;
    var keys = Object.keys(dom);
    for (var i = 0; i < keys.length; i++) {
      if (
        keys[i].indexOf("__reactFiber$") === 0 ||
        keys[i].indexOf("__reactInternalInstance$") === 0
      ) {
        return dom[keys[i]];
      }
    }
    return null;
  }

  function findLeftPanelReactApi(sep) {
    var fiber = getReactFiber(sep);
    var steps = 0;
    var found = { handle: null, onSeparatorClick: null, onDoubleClick: null };
    while (fiber && steps < 60) {
      var props = fiber.memoizedProps || fiber.pendingProps;
      if (props) {
        if (!found.onSeparatorClick && typeof props.onSeparatorClick === "function") {
          found.onSeparatorClick = props.onSeparatorClick;
        }
        if (!found.onDoubleClick && typeof props.onDoubleClick === "function") {
          found.onDoubleClick = props.onDoubleClick;
        }
        var handle = props.panelHandle || props.handle || props.resizeHandle;
        if (
          handle &&
          (typeof handle.resize === "function" ||
            typeof handle.collapse === "function")
        ) {
          found.handle = handle;
        }
      }
      fiber = fiber.return;
      steps++;
    }
    return found;
  }

  /** 单击展开：优先 panelHandle.resize / onSeparatorClick（勿用 dblclick） */
  function tryReactLeftPanelExpand(sep) {
    var api = findLeftPanelReactApi(sep);
    if (api.handle && typeof api.handle.resize === "function") {
      try {
        var w =
          api.handle.defaultSize ||
          api.handle.collapsedSize ||
          api.handle.minSize ||
          260;
        if (typeof w !== "number" || w < 120) w = 260;
        api.handle.resize(w);
        return true;
      } catch (_e0) {
        /* ignore */
      }
    }
    if (api.handle && typeof api.handle.expand === "function") {
      try {
        api.handle.expand();
        return true;
      } catch (_e1) {
        /* ignore */
      }
    }
    if (api.onSeparatorClick) {
      try {
        api.onSeparatorClick();
        return true;
      } catch (_e2) {
        /* ignore */
      }
    }
    return false;
  }

  /** 单击收起：优先 panelHandle.collapse / resize(0)；API 失败再静默调 onDoubleClick */
  function tryReactLeftPanelCollapse(sep) {
    var api = findLeftPanelReactApi(sep);
    if (api.handle && typeof api.handle.collapse === "function") {
      try {
        api.handle.collapse();
        return true;
      } catch (_e0) {
        /* ignore */
      }
    }
    if (api.handle && typeof api.handle.resize === "function") {
      try {
        api.handle.resize(0);
        return true;
      } catch (_e1) {
        /* ignore */
      }
    }
    if (api.onDoubleClick) {
      try {
        api.onDoubleClick({
          type: "dblclick",
          preventDefault: function () {},
          stopPropagation: function () {},
        });
        return true;
      } catch (_e2) {
        /* ignore */
      }
    }
    return false;
  }

  /**
   * 单击展开：先解除我们的压宽，再 resize / 单次 pointerdown→pointerup。
   * 绝不派发 dblclick（那是收起路径）。
   */
  function expandLeftPanelViaSeparator(sep) {
    if (!sep) return;
    var wasBar = sep.getAttribute("data-separator-type") === "bar";
    beginLeftPanelExpanding();

    /* 1) 先 React resize（单击即可，不依赖用户双击） */
    tryReactLeftPanelExpand(sep);

    /* 2) 仅当官方仍是 bar 折叠态时，补一次 pointerdown→up（Element 折叠条单击展开） */
    if (wasBar || sep.getAttribute("data-separator-type") === "bar") {
      sep.style.setProperty("pointer-events", "auto", "important");
      sep.style.setProperty("width", "12px", "important");
      sep.style.setProperty("min-width", "12px", "important");
      sep.style.setProperty("max-width", "12px", "important");
      sep.style.setProperty("opacity", "0", "important");
      sep.style.setProperty("flex", "0 0 12px", "important");

      var space = document.querySelector(".mx_SpacePanel");
      var spaceRect = space ? space.getBoundingClientRect() : null;
      var pt = leftPanelSeparatorPoint(sep);
      if (spaceRect && spaceRect.width > 0) {
        pt.x = spaceRect.right + 6;
        pt.y = Math.min(
          Math.max(spaceRect.top + spaceRect.height / 2, 40),
          window.innerHeight - 40
        );
      }
      try {
        fireLeftPanelPointer(sep, "pointerdown", pt.x, pt.y, 1);
        fireLeftPanelPointer(sep, "pointerup", pt.x, pt.y, 0);
      } catch (_e) {
        /* ignore */
      }
      tryReactLeftPanelExpand(sep);
    }

    setTimeout(function () {
      try {
        sep.style.removeProperty("pointer-events");
        sep.style.removeProperty("width");
        sep.style.removeProperty("min-width");
        sep.style.removeProperty("max-width");
        sep.style.removeProperty("opacity");
        sep.style.removeProperty("flex");
      } catch (_c) {
        /* ignore */
      }
      var s2 = findLeftPanelSeparator();
      /* 若仍 bar，再 resize 一次（仍是单击语义，不是 dblclick） */
      if (s2 && s2.getAttribute("data-separator-type") === "bar") {
        tryReactLeftPanelExpand(s2);
      }
      if (!s2 || s2.getAttribute("data-separator-type") !== "bar") {
        endLeftPanelExpanding();
      }
      enhanceLeftPanelToggle();
    }, 100);

    setTimeout(function () {
      var s3 = findLeftPanelSeparator();
      if (s3 && s3.getAttribute("data-separator-type") === "bar") {
        tryReactLeftPanelExpand(s3);
      } else {
        endLeftPanelExpanding();
      }
      enhanceLeftPanelToggle();
    }, 280);
  }

  /**
   * 单击收起：只触发 Element 官方 collapse / resize(0)。
   * 不再内联 crushZero（定时器曾在展开态反复 width:0 → 虚拟列表高度永久为 0）。
   */
  function collapseLeftPanelViaSeparator(sep) {
    if (!sep) return;
    endLeftPanelExpanding();
    armUserCollapse();
    setRoomListCollapsedFlag(true);
    tryReactLeftPanelCollapse(sep);
    setTimeout(function () {
      var s2 = findLeftPanelSeparator() || sep;
      var type = s2 && s2.getAttribute("data-separator-type");
      /* 仅当官方已确认 bar 时保留折叠标；否则立刻放行，防误压列表 */
      if (type === "bar") {
        setRoomListCollapsedFlag(true);
      } else if (type && type !== "bar") {
        disarmUserCollapse();
        setRoomListCollapsedFlag(false);
        releaseCollapsedRoomListStyles();
        nudgeRoomListLayout();
      }
      enhanceLeftPanelToggle();
    }, 80);
    setTimeout(function () {
      enhanceLeftPanelToggle();
    }, 240);
  }

  function isRoomListCollapsedUi(sep) {
    if (leftPanelExpanding) return false;
    var type = sep && sep.getAttribute("data-separator-type");
    /*
     * 唯一真相：Element data-separator-type === "bar"。
     * 禁止回退到粘滞 leftPanelForcedCollapsed / body 属性——
     * 旧逻辑会在展开态每 1.5s 再 crush，刷新后短暂正常随后空白。
     */
    if (type === "bar") return true;
    return false;
  }

  function enhanceLeftPanelToggle() {
    var sep = findLeftPanelSeparator();
    var btn = document.getElementById("jingepi-left-panel-toggle");
    if (!sep) {
      if (btn) btn.remove();
      /* 无分隔线：永远展开，清掉残留 crush / 粘滞标 */
      if (
        leftPanelForcedCollapsed ||
        (document.body &&
          document.body.getAttribute("data-jingepi-roomlist-collapsed") === "1")
      ) {
        disarmUserCollapse();
        setRoomListCollapsedFlag(false);
        releaseCollapsedRoomListStyles();
        nudgeRoomListLayout();
      }
      return;
    }

    var type = sep.getAttribute("data-separator-type") || "";
    /* 展开过程中勿因 bar 残帧把折叠标打回去 */
    if (type === "bar" && !leftPanelExpanding) {
      setRoomListCollapsedFlag(true);
    } else {
      /* 非 bar（含空 type）：默认展开，禁止粘滞折叠标 */
      if (
        leftPanelForcedCollapsed ||
        (document.body &&
          document.body.getAttribute("data-jingepi-roomlist-collapsed") === "1")
      ) {
        setRoomListCollapsedFlag(false);
        releaseCollapsedRoomListStyles();
        nudgeRoomListLayout();
      } else {
        setRoomListCollapsedFlag(false);
      }
      disarmUserCollapse();
      if (leftPanelExpanding && type && type !== "bar") {
        endLeftPanelExpanding();
      }
    }
    var collapsed = isRoomListCollapsedUi(sep) && !leftPanelExpanding;
    if (!collapsed && leftPanelExpanding && type !== "bar") {
      endLeftPanelExpanding();
    }

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
        if (isRoomListCollapsedUi(s)) {
          expandLeftPanelViaSeparator(s);
        } else {
          collapseLeftPanelViaSeparator(s);
        }
      });
      (document.body || document.documentElement).appendChild(btn);
    }

    var nextState = collapsed ? "collapsed" : "expanded";
    var prevState = btn.getAttribute("data-jingepi-panel-state") || "";
    var prevLabel = btn.getAttribute("data-jingepi-label") || "";
    if (collapsed) {
      if (prevLabel !== "expand-2line" || prevState !== "collapsed") {
        btn.innerHTML =
          '<span class="jingepi-toggle-line">展开所有</span>' +
          '<span class="jingepi-toggle-line">频道与群组</span>';
        btn.setAttribute("data-jingepi-label", "expand-2line");
      }
      btn.setAttribute("aria-label", "展开所有频道与群组");
      btn.setAttribute("title", "展开所有频道与群组");
    } else {
      if (prevLabel !== "collapse" || prevState !== "expanded") {
        btn.textContent = "收起";
        btn.setAttribute("data-jingepi-label", "collapse");
      }
      btn.setAttribute("aria-label", "收起侧栏");
      btn.setAttribute("title", "收起");
    }
    btn.setAttribute("data-jingepi-panel-state", nextState);

    /*
     * 折叠：水平锚在 Space 窄栏中心（与 Home/+ 同竖轴），translateX(-50%)；
     *       勿用 spaceRect.right——会把整颗两行按钮甩进主内容区。
     * 展开：仍骑分隔线中线，相对顶 +38。
     * 窄屏（≤900）：QQ 列表↔聊天，隐藏「展开所有」浮钮（改用顶栏返回 + 底栏频道）。
     */
    var rect = sep.getBoundingClientRect();
    var cx = rect.left + Math.max(rect.width, 1) / 2;
    var topY = rect.top + LEFT_PANEL_TOP_PAD;
    var mobileSpaceBar = isMobileViewport();
    if (mobileSpaceBar) {
      document.body &&
        document.body.setAttribute("data-jingepi-mobile-spacebar", "1");
      btn.style.display = "none";
      forceCollapsedRoomListColumn(collapsed, sep);
      return;
    } else {
      document.body &&
        document.body.removeAttribute("data-jingepi-mobile-spacebar");
      btn.style.display = "";
      if (collapsed) {
        var space = document.querySelector(".mx_SpacePanel");
        var spaceRect = space ? space.getBoundingClientRect() : null;
        var homeBtn =
          document.querySelector(
            ".mx_SpacePanel .mx_SpaceButton_home .mx_SpaceButton_selectionWrapper"
          ) ||
          document.querySelector(
            ".mx_SpacePanel .mx_SpaceButton.mx_SpaceButton_narrow .mx_SpaceButton_selectionWrapper"
          ) ||
          document.querySelector(
            ".mx_SpacePanel .mx_SpaceButton.mx_SpaceButton_narrow"
          );
        /* 优先外层「+」按钮整颗 rect，勿用内层 selectionWrapper（底边偏上会重叠） */
        var plusBtn =
          document.querySelector(".mx_SpacePanel .mx_SpaceButton_newPlace") ||
          document.querySelector(".mx_SpacePanel .mx_SpaceButton.newRoom") ||
          document.querySelector(
            ".mx_SpacePanel [aria-label*='创建'], .mx_SpacePanel [aria-label*='Create'], .mx_SpacePanel [aria-label*='新建']"
          );
        if (homeBtn) {
          var hr = homeBtn.getBoundingClientRect();
          /* 与主页金框同列中心 */
          cx = hr.left + hr.width / 2;
        } else if (spaceRect && spaceRect.width > 0) {
          cx = spaceRect.left + spaceRect.width / 2;
        } else if (!isFinite(cx) || (rect.width === 0 && rect.height === 0)) {
          cx = 34;
        }
        if (plusBtn) {
          var pr = plusBtn.getBoundingClientRect();
          /* 顶边 = + 底边 + 8，整颗在加号下方、完全不重叠 */
          topY = pr.bottom + 8;
        } else if (homeBtn) {
          /* 无 + 时多留空，避免盖住常见加号位 */
          topY = homeBtn.getBoundingClientRect().bottom + 72;
        } else if (spaceRect) {
          topY = spaceRect.top + 120;
        }
      } else if (!isFinite(cx) || (rect.width === 0 && rect.height === 0)) {
        cx = 260;
      }
    }
    if (!isFinite(topY)) {
      topY = LEFT_PANEL_TOP_PAD;
    }
    cx = Math.max(18, Math.min(cx, window.innerWidth - 18));
    topY = Math.max(8, Math.min(topY, window.innerHeight - 40));
    btn.style.left = Math.round(cx) + "px";
    btn.style.top = Math.round(topY) + "px";
    btn.style.right = "auto";
    btn.style.bottom = "auto";
    btn.style.transform = "translateX(-50%)";

    /*
     * 定时器路径：只同步 flag / 清残留，绝不 crush。
     * crush 仅在用户点收起且 separator 已是 bar 时由 forceCollapsed… 短路（现已禁用内联压宽）。
     */
    forceCollapsedRoomListColumn(collapsed, sep);
  }

  /**
   * 折叠态同步：默认永不内联 crush（width:0 / flex:0）。
   * 根因：定时 suppress→enhanceLeftPanelToggle 曾反复 crushZero，
   * 把 .mx_RoomList 压成 flex:0 → 虚拟列表高度永久为 0（筛选条还在、下方空白）。
   * 收起只靠 Element 原生 collapse + CSS data-jingepi-roomlist-collapsed。
   */
  function forceCollapsedRoomListColumn(collapsed, sep) {
    if (leftPanelExpanding) return;

    var type = sep && sep.getAttribute("data-separator-type");

    /* 硬守卫：非 bar 一律当展开；禁止定时器在展开态 crush */
    if (type !== "bar") {
      if (
        leftPanelForcedCollapsed ||
        (document.body &&
          document.body.getAttribute("data-jingepi-roomlist-collapsed") === "1") ||
        document.querySelector("[data-jingepi-collapsed-col]")
      ) {
        jingepiRoomListLog("guard: release (type!=bar)", type);
        setRoomListCollapsedFlag(false);
        releaseCollapsedRoomListStyles();
        nudgeRoomListLayout();
      }
      syncMobileSpaceBar();
      return;
    }

    if (!collapsed) {
      setRoomListCollapsedFlag(false);
      releaseCollapsedRoomListStyles();
      nudgeRoomListLayout();
      syncMobileSpaceBar();
      return;
    }

    /*
     * type===bar 且 collapsed：只打 CSS 标，不写内联 width:0。
     * 即便用户刚点收起，也交给 Element panelHandle.collapse；
     * 旧 crushZero / fitSpaceOnly 已移除。
     */
    if (!leftPanelUserCollapseArmed && !leftPanelForcedCollapsed) {
      /* 官方已是 bar（例如用户拖到折叠）：同步标即可 */
      jingepiRoomListLog("bar sync flag only (no crush)");
    } else {
      jingepiRoomListLog("bar collapsed (no crushZero)", {
        armed: leftPanelUserCollapseArmed,
      });
    }
    setRoomListCollapsedFlag(true);
    /* 若历史残留内联 crush，清掉以免和官方折叠叠加重伤布局 */
    if (document.querySelector("[data-jingepi-collapsed-col]")) {
      releaseCollapsedRoomListStyles();
    }
    syncMobileSpaceBar();
  }

  /** 房间信息 / RoomSummary 右侧栏是否打开 */
  function isRoomInfoPanelOpen() {
    var nodes = document.querySelectorAll(
      [
        ".mx_RoomSummaryCard",
        ".mx_RoomSummaryCardView",
        ".mx_RoomInfo",
        ".mx_RightPanel .mx_RoomSummaryCard",
        ".mx_RightPanel .mx_BaseCard",
        "[data-testid='room-summary-card']",
        ".mx_BaseCard_header",
      ].join(",")
    );
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var r = el.getBoundingClientRect();
      if (r.width < 8 || r.height < 8) continue;
      /* BaseCard 也可能是其它卡片：优先 Summary / 标题含房间信息 */
      if (
        el.classList.contains("mx_RoomSummaryCard") ||
        el.classList.contains("mx_RoomSummaryCardView") ||
        el.classList.contains("mx_RoomInfo") ||
        el.getAttribute("data-testid") === "room-summary-card"
      ) {
        return true;
      }
      if (el.classList.contains("mx_BaseCard_header") || el.classList.contains("mx_BaseCard")) {
        var text = (el.textContent || "").replace(/\s+/g, " ").trim();
        if (/房间信息|Room info|Room details|About this room|关于此房间/i.test(text)) {
          return true;
        }
        if (
          el.closest &&
          el.closest(".mx_RightPanel") &&
          el.querySelector &&
          el.querySelector(".mx_RoomTopic, .mx_RoomSummaryCard, .mx_RoomHeader_topic")
        ) {
          return true;
        }
      }
    }
    var rp = document.querySelector(".mx_RightPanel, .mx_RightPanel_ResizeWrapper");
    if (rp) {
      var rr = rp.getBoundingClientRect();
      if (rr.width > 40) {
        if (
          rp.querySelector(
            ".mx_RoomSummaryCard, .mx_RoomSummaryCardView, .mx_RoomInfo, [data-testid='room-summary-card']"
          )
        ) {
          return true;
        }
        var h = rp.querySelector("h1, h2, [role='heading'], .mx_BaseCard_header");
        if (h) {
          var ht = (h.textContent || "").replace(/\s+/g, " ").trim();
          if (/^(房间信息|Room info|Room details|About)$/i.test(ht)) return true;
        }
      }
    }
    return false;
  }

  function syncRoomInfoMoreVisibility() {
    var open = isRoomInfoPanelOpen();
    try {
      if (document.body) {
        if (open) {
          document.body.setAttribute("data-jingepi-room-info-open", "1");
        } else {
          document.body.removeAttribute("data-jingepi-room-info-open");
        }
      }
    } catch (_e) {
      /* ignore */
    }
    var wrap = document.getElementById("jingepi-room-header-more");
    var panel = getHeaderMorePanel();
    if (open) {
      if (wrap) {
        wrap.style.setProperty("display", "none", "important");
        wrap.setAttribute("aria-hidden", "true");
      }
      if (panel) {
        closeHeaderMorePanel();
        panel.style.setProperty("display", "none", "important");
      }
    } else {
      if (wrap) {
        wrap.style.removeProperty("display");
        wrap.removeAttribute("aria-hidden");
      }
      if (panel && panel.getAttribute("data-open") !== "1") {
        panel.style.removeProperty("display");
      }
    }
    return open;
  }

  function collapseRoomHeaderActions() {
    if (headerMoreActivating) return;
    if (syncRoomInfoMoreVisibility()) {
      /* 房间信息打开：不重建更多按钮，避免叠到右侧「搜索」 */
      return;
    }
    var headers = document.querySelectorAll(
      "header.mx_RoomHeader, .mx_RoomHeader, .mx_LegacyRoomHeader"
    );
    if (!headers.length) {
      var orphan = document.getElementById("jingepi-room-header-more");
      var orphanPanel = getHeaderMorePanel();
      if (orphanPanel) orphanPanel.remove();
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
      /* 打开中时保持 body portal + 定位 */
      if (getHeaderMorePanel() && getHeaderMorePanel().getAttribute("data-open") === "1") {
        openHeaderMorePanel();
      }
    }
  }

  /* ---- 窄屏消息输入四段：[更多] [输入] [语音] [表情] ---- */
  var COMPOSER_KEEP_RE =
    /表情|emoji|贴纸|sticker|语音消息|voice message|send voice|麦克风|microphone/i;
  var COMPOSER_OVERFLOW_RE =
    /附件|attachment|attach|upload|上传|文件|poll|投票|位置|location|格式|formatting|plain text|rich text|纯文本|富文本|更多选项|more options|更多操作/i;
  var COMPOSER_VOICE_CTRL_RE =
    /^(删除|Delete|取消|Cancel|停止录音|停止|Stop recording|Stop the recording)$/i;

  function isComposerMobile() {
    try {
      return window.matchMedia("(max-width: 900px)").matches;
    } catch (_e) {
      return false;
    }
  }

  function isVoiceRecordingUi(el) {
    if (!el || !el.closest) return false;
    return !!(
      el.closest(".mx_VoiceRecordComposerTile_delete") ||
      el.closest(".mx_VoiceRecordComposerTile_stop") ||
      el.closest(".mx_VoiceMessagePrimaryContainer") ||
      el.closest(".mx_VoiceRecordComposerTile_recording") ||
      el.closest(".mx_VoiceRecordComposerTile_uploadingState") ||
      el.closest(".mx_VoiceRecordComposerTile_failedState") ||
      (el.classList &&
        (el.classList.contains("mx_VoiceRecordComposerTile_delete") ||
          el.classList.contains("mx_VoiceRecordComposerTile_stop") ||
          el.classList.contains("mx_VoiceMessagePrimaryContainer")))
    );
  }

  function composerIsRecording(root) {
    if (!root || !root.querySelector) return false;
    return !!(
      root.querySelector(".mx_VoiceRecordComposerTile_delete") ||
      root.querySelector(".mx_VoiceRecordComposerTile_stop") ||
      root.querySelector(".mx_VoiceMessagePrimaryContainer") ||
      root.querySelector(".mx_VoiceRecordComposerTile_recording")
    );
  }

  function composerBtnLabel(btn) {
    return (
      btn.getAttribute("aria-label") ||
      btn.getAttribute("title") ||
      ""
    )
      .replace(/\s+/g, " ")
      .trim();
  }

  function getReactFiber(node) {
    if (!node) return null;
    var keys = Object.keys(node);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (
        k.indexOf("__reactFiber$") === 0 ||
        k.indexOf("__reactInternalInstance$") === 0
      ) {
        return node[k];
      }
    }
    return null;
  }

  function findComposerController(fromEl) {
    var fiber = getReactFiber(fromEl);
    var hops = 0;
    while (fiber && hops < 40) {
      var sn = fiber.stateNode;
      if (
        sn &&
        typeof sn.onRecordStartEndClick === "function" &&
        sn.voiceRecordingButton !== undefined
      ) {
        return sn;
      }
      if (
        sn &&
        typeof sn.onRecordStartEndClick === "function"
      ) {
        return sn;
      }
      fiber = fiber.return;
      hops++;
    }
    return null;
  }

  function findNativeComposerMenu(row) {
    if (!row) return null;
    return (
      row.querySelector(".mx_MessageComposer_buttonMenu") ||
      row.querySelector(
        ".mx_MessageComposer_actions .mx_MessageComposer_button[aria-haspopup]"
      ) ||
      null
    );
  }

  function classifyComposerButton(btn) {
    if (!btn || btn.id === "jingepi-composer-voice") return "skip";
    if (btn.closest && btn.closest("#jingepi-composer-more")) return "skip";
    if (isVoiceRecordingUi(btn)) return "voice_ctrl";
    if (
      btn.classList.contains("mx_VoiceRecordComposerTile_delete") ||
      btn.classList.contains("mx_VoiceRecordComposerTile_stop")
    ) {
      return "voice_ctrl";
    }
    if (btn.classList.contains("mx_MessageComposer_sendMessage")) return "send";
    if (btn.classList.contains("mx_MessageComposer_buttonMenu")) return "menu";
    if (btn.classList.contains("mx_MessageComposer_emoji")) return "emoji";
    if (btn.classList.contains("mx_MessageComposer_stickers")) return "stickers";
    if (btn.classList.contains("mx_MessageComposer_voiceMessage")) return "voice";
    if (
      btn.classList.contains("mx_MessageComposer_upload") ||
      btn.classList.contains("mx_MessageComposer_poll") ||
      btn.classList.contains("mx_MessageComposer_location") ||
      btn.classList.contains("mx_MessageComposer_plain_text") ||
      btn.classList.contains("mx_MessageComposer_rich_text")
    ) {
      return "overflow";
    }
    var label = composerBtnLabel(btn);
    if (COMPOSER_VOICE_CTRL_RE.test(label)) return "voice_ctrl";
    if (COMPOSER_KEEP_RE.test(label)) {
      if (/语音|voice|麦克风|microphone/i.test(label)) return "voice";
      if (/贴纸|sticker/i.test(label)) return "stickers";
      return "emoji";
    }
    if (COMPOSER_OVERFLOW_RE.test(label)) return "overflow";
    /* 未知图标钮：默认收纳，避免挤占输入宽度 */
    if (btn.querySelector && btn.querySelector("svg")) return "overflow";
    return "skip";
  }

  function ensureComposerMoreUi(row) {
    var wrap = document.getElementById("jingepi-composer-more");
    if (wrap && !row.contains(wrap)) {
      wrap.remove();
      wrap = null;
    }
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.id = "jingepi-composer-more";
      wrap.setAttribute("data-jingepi-composer-slot", "more");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("aria-label", "更多");
      btn.setAttribute("title", "更多");
      btn.textContent = "⋯";
      function stopComposerMoreBubble(ev) {
        try {
          ev.stopPropagation();
        } catch (_eStop) {
          /* ignore */
        }
      }
      btn.addEventListener("pointerdown", stopComposerMoreBubble, true);
      btn.addEventListener("mousedown", stopComposerMoreBubble, true);
      btn.addEventListener("click", function (ev) {
        try {
          ev.preventDefault();
        } catch (_ePrev) {
          /* ignore */
        }
        stopComposerMoreBubble(ev);
        var menu = findNativeComposerMenu(row);
        if (menu) {
          /* 瞬时恢复可点，再触发 Element 自带 overflow */
          var prev = menu.getAttribute("data-jingepi-composer-overflow");
          menu.removeAttribute("data-jingepi-composer-overflow");
          menu.style.setProperty("pointer-events", "auto", "important");
          menu.style.setProperty("opacity", "0", "important");
          menu.style.setProperty("position", "fixed", "important");
          menu.style.setProperty("left", "8px", "important");
          menu.style.setProperty("bottom", "8px", "important");
          menu.style.setProperty("z-index", "2147483001", "important");
          fireDomClick(menu);
          setTimeout(function () {
            try {
              menu.removeAttribute("style");
              if (prev) menu.setAttribute("data-jingepi-composer-overflow", prev);
              else menu.setAttribute("data-jingepi-composer-overflow", "1");
            } catch (_e) {
              /* ignore */
            }
          }, 160);
          return;
        }
        /* 无原生菜单时：点第一个被收纳的按钮（附件优先） */
        var upload =
          row.querySelector(".mx_MessageComposer_upload") ||
          row.querySelector("[data-jingepi-composer-overflow='1']");
        if (upload) fireDomClick(upload);
      });
      wrap.appendChild(btn);
    }
    var composer =
      row.querySelector(".mx_SendWysiwygComposer") ||
      row.querySelector(".mx_SendMessageComposer") ||
      row.querySelector(".mx_BasicMessageComposer") ||
      row.querySelector(".mx_MessageComposer_input_wrapper");
    if (wrap.parentElement !== row) {
      if (composer) row.insertBefore(wrap, composer);
      else row.insertBefore(wrap, row.firstChild);
    } else if (composer && wrap.nextSibling !== composer) {
      row.insertBefore(wrap, composer);
    }
    return wrap;
  }

  function ensureComposerVoiceUi(row, actions) {
    var nativeVoice =
      row.querySelector(".mx_MessageComposer_voiceMessage") ||
      (actions && actions.querySelector(".mx_MessageComposer_voiceMessage"));
    if (nativeVoice) {
      nativeVoice.setAttribute("data-jingepi-composer-keep", "voice");
      var injected = document.getElementById("jingepi-composer-voice");
      if (injected) injected.remove();
      return nativeVoice;
    }
    var voice = document.getElementById("jingepi-composer-voice");
    if (voice && !row.contains(voice) && !(actions && actions.contains(voice))) {
      voice.remove();
      voice = null;
    }
    if (!voice) {
      voice = document.createElement("button");
      voice.type = "button";
      voice.id = "jingepi-composer-voice";
      voice.setAttribute("data-jingepi-composer-keep", "voice");
      voice.setAttribute("aria-label", "语音消息");
      voice.setAttribute("title", "语音消息");
      voice.innerHTML =
        '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false"><path fill="currentColor" d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z"/></svg>';
      voice.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var host =
          row.closest(".mx_MessageComposer") ||
          document.querySelector(".mx_MessageComposer");
        var ctrl = findComposerController(host || row);
        if (ctrl && typeof ctrl.onRecordStartEndClick === "function") {
          try {
            ctrl.onRecordStartEndClick();
            return;
          } catch (_e0) {
            /* fall through */
          }
        }
        /* 再试：打开原生更多菜单里的语音（宽屏模式） */
        var menu = findNativeComposerMenu(row);
        if (menu) fireDomClick(menu);
      });
    }
    var mount = actions || row;
    if (voice.parentElement !== mount) {
      mount.appendChild(voice);
    }
    return voice;
  }

  function cleanupComposerLayout() {
    var more = document.getElementById("jingepi-composer-more");
    if (more) more.remove();
    var voice = document.getElementById("jingepi-composer-voice");
    if (voice) voice.remove();
    var marked = document.querySelectorAll(
      "[data-jingepi-composer-overflow], [data-jingepi-composer-keep]"
    );
    for (var i = 0; i < marked.length; i++) {
      marked[i].removeAttribute("data-jingepi-composer-overflow");
      marked[i].removeAttribute("data-jingepi-composer-keep");
    }
    var recordingRoots = document.querySelectorAll(
      ".mx_MessageComposer[data-jingepi-recording]"
    );
    for (var r = 0; r < recordingRoots.length; r++) {
      recordingRoots[r].removeAttribute("data-jingepi-recording");
    }
  }

  function isComposerIconCandidate(el) {
    if (!el || el.nodeType !== 1) return false;
    if (el.classList.contains("mx_VoiceRecordComposerTile_delete")) return false;
    if (el.classList.contains("mx_VoiceRecordComposerTile_stop")) return false;
    if (el.getAttribute("data-jingepi-composer-keep") === "voice-ctrl") return false;
    if (el.closest && el.closest(".mx_VoiceMessagePrimaryContainer")) return false;
    if (el.getAttribute("contenteditable") === "true") return false;
    if (el.getAttribute("role") === "textbox") return false;
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") return false;
    if (el.classList.contains("mx_BasicMessageComposer_input")) return false;
    if (el.classList.contains("mx_WysiwygComposer_Editor_content")) return false;
    return true;
  }

  /**
   * 桌面+窄屏：给输入栏旁每个操作图标钮打 data-jingepi-composer-icon，
   * CSS 靠该属性强制同一套圆玻璃（避免外壳透明规则/类名差异再漏）。
   * 真实 DOM：表情=mx_EmojiButton(div)，附件=Compound _icon-button_(button)，更多=buttonMenu(div)。
   */
  function tagComposerIconButtons() {
    var GLASS_BG =
      "linear-gradient(155deg, rgba(255,255,255,.12) 0%, rgba(80,80,86,.1) 38%, rgba(0,0,0,.2) 100%), rgba(36,36,40,.62)";
    var composers = document.querySelectorAll(".mx_MessageComposer");
    for (var c = 0; c < composers.length; c++) {
      var root = composers[c];
      var stale = root.querySelectorAll("[data-jingepi-composer-icon]");
      for (var s = 0; s < stale.length; s++) {
        stale[s].removeAttribute("data-jingepi-composer-icon");
      }
      var nodes = root.querySelectorAll(
        [
          ".mx_MessageComposer_emoji",
          ".mx_EmojiButton",
          ".mx_MessageComposer_stickers",
          ".mx_MessageComposer_upload",
          ".mx_MessageComposer_buttonMenu",
          ".mx_MessageComposer_voiceMessage",
          ".mx_MessageComposer_poll",
          ".mx_MessageComposer_location",
          ".mx_MessageComposer_plain_text",
          ".mx_MessageComposer_rich_text",
          ".mx_MessageComposer_sendMessage",
          ".mx_MessageComposer_button",
          ".mx_MessageComposer_actions > button",
          ".mx_MessageComposer_actions > [role='button']",
          ".mx_MessageComposer_actions > .mx_AccessibleButton",
          ".mx_MessageComposer_actions > .cpd-button",
          ".mx_MessageComposer_actions [class*='_icon-button_']",
          ".mx_MessageComposer_row > button",
          ".mx_MessageComposer_row > [role='button']",
          ".mx_MessageComposer_row > .mx_AccessibleButton",
          "#jingepi-composer-more > button",
          "#jingepi-composer-voice",
        ].join(",")
      );
      for (var i = 0; i < nodes.length; i++) {
        var btn = nodes[i];
        if (!isComposerIconCandidate(btn)) continue;
        btn.setAttribute("data-jingepi-composer-icon", "1");
        /* 内联 !important：压过 Compound / 外壳透明，保证三钮肉眼同形 */
        btn.style.setProperty("width", "36px", "important");
        btn.style.setProperty("height", "36px", "important");
        btn.style.setProperty("min-width", "36px", "important");
        btn.style.setProperty("min-height", "36px", "important");
        btn.style.setProperty("padding", "0", "important");
        btn.style.setProperty("border-radius", "50%", "important");
        btn.style.setProperty("background", GLASS_BG, "important");
        btn.style.setProperty("background-color", "rgba(36,36,40,.62)", "important");
        btn.style.setProperty("border", "1px solid rgba(255,255,255,.14)", "important");
        btn.style.setProperty(
          "box-shadow",
          "inset 0 1px 0 rgba(255,255,255,.32), inset 0 -1px 0 rgba(0,0,0,.28)",
          "important"
        );
        btn.style.setProperty("display", "inline-flex", "important");
        btn.style.setProperty("align-items", "center", "important");
        btn.style.setProperty("justify-content", "center", "important");
        btn.style.setProperty("color", "var(--jp-text-muted, #aaaaaa)", "important");
        btn.style.setProperty("--cpd-icon-button-size", "36px", "important");
        var svgs = btn.querySelectorAll("svg");
        for (var v = 0; v < svgs.length; v++) {
          svgs[v].style.setProperty("width", "20px", "important");
          svgs[v].style.setProperty("height", "20px", "important");
        }
      }
    }
    var moreBtn = document.querySelector("#jingepi-composer-more > button");
    if (moreBtn) moreBtn.setAttribute("data-jingepi-composer-icon", "1");
    var voiceBtn = document.getElementById("jingepi-composer-voice");
    if (voiceBtn && isComposerIconCandidate(voiceBtn)) {
      voiceBtn.setAttribute("data-jingepi-composer-icon", "1");
    }
  }

  function layoutComposerMobile() {
    if (!isComposerMobile()) {
      cleanupComposerLayout();
      tagComposerIconButtons();
      return;
    }
    var composers = document.querySelectorAll(".mx_MessageComposer");
    if (!composers.length) return;

    for (var c = 0; c < composers.length; c++) {
      var root = composers[c];
      var row =
        root.querySelector(".mx_MessageComposer_row") ||
        root.querySelector(".mx_MessageComposer_wrapper > div");
      if (!row) continue;
      var actions = row.querySelector(".mx_MessageComposer_actions");
      var recording = composerIsRecording(root);

      if (recording) {
        root.setAttribute("data-jingepi-recording", "1");
      } else {
        root.removeAttribute("data-jingepi-recording");
      }

      /* 录音中仍挂「更多」节点（CSS 会藏），结束录音后立刻可用 */
      ensureComposerMoreUi(row);

      var buttons = row.querySelectorAll(
        "button, [role='button'], .mx_AccessibleButton, .mx_MessageComposer_button"
      );
      var hasEmoji = false;
      var hasStickers = false;
      for (var i = 0; i < buttons.length; i++) {
        var btn = buttons[i];
        if (btn.closest("#jingepi-composer-more")) continue;
        if (btn.id === "jingepi-composer-voice") continue;
        var kind = classifyComposerButton(btn);
        if (kind === "voice_ctrl") {
          btn.setAttribute("data-jingepi-composer-keep", "voice-ctrl");
          btn.removeAttribute("data-jingepi-composer-overflow");
        } else if (kind === "emoji") {
          btn.setAttribute("data-jingepi-composer-keep", "emoji");
          btn.removeAttribute("data-jingepi-composer-overflow");
          hasEmoji = true;
        } else if (kind === "stickers") {
          btn.setAttribute("data-jingepi-composer-keep", "stickers");
          btn.removeAttribute("data-jingepi-composer-overflow");
          hasStickers = true;
        } else if (kind === "voice") {
          btn.setAttribute("data-jingepi-composer-keep", "voice");
          btn.removeAttribute("data-jingepi-composer-overflow");
        } else if (kind === "menu" || kind === "overflow") {
          /* 录音态勿把 VoiceRecord 控件误标 overflow（已由 voice_ctrl 拦截） */
          btn.setAttribute("data-jingepi-composer-overflow", "1");
          btn.removeAttribute("data-jingepi-composer-keep");
        } else if (kind === "send") {
          btn.removeAttribute("data-jingepi-composer-overflow");
        }
      }

      /* 录音态：勿再注入/强化空闲语音钮；确保波形容器不被 overflow 规则影响 */
      if (recording) {
        var voiceCtrls = root.querySelectorAll(
          ".mx_VoiceRecordComposerTile_delete, .mx_VoiceRecordComposerTile_stop, .mx_VoiceMessagePrimaryContainer"
        );
        for (var v = 0; v < voiceCtrls.length; v++) {
          voiceCtrls[v].setAttribute("data-jingepi-composer-keep", "voice-ctrl");
          voiceCtrls[v].removeAttribute("data-jingepi-composer-overflow");
        }
        var injectedBusy = document.getElementById("jingepi-composer-voice");
        if (injectedBusy) injectedBusy.style.setProperty("display", "none", "important");
        continue;
      }

      /* 窄屏 Element 常不渲染语音钮：注入并挂到 actions 右侧前 */
      ensureComposerVoiceUi(row, actions);
      var injectedIdle = document.getElementById("jingepi-composer-voice");
      if (injectedIdle) injectedIdle.style.removeProperty("display");

      /* 表情与贴纸同时露出时只留表情，贴纸进更多 */
      if (hasEmoji && hasStickers) {
        var stickerBtns = row.querySelectorAll(
          "[data-jingepi-composer-keep='stickers']"
        );
        for (var s = 0; s < stickerBtns.length; s++) {
          stickerBtns[s].setAttribute("data-jingepi-composer-overflow", "1");
          stickerBtns[s].removeAttribute("data-jingepi-composer-keep");
        }
      }

      /* 表情优先露出；若只有贴纸也保留 */
      if (!hasEmoji && !hasStickers && actions) {
        var fallbackEmoji =
          actions.querySelector("[aria-label*='表情']") ||
          actions.querySelector("[aria-label*='Emoji']") ||
          actions.querySelector("[aria-label*='emoji']") ||
          actions.querySelector("[title*='表情']") ||
          actions.querySelector("[title*='Emoji']");
        if (fallbackEmoji) {
          fallbackEmoji.setAttribute("data-jingepi-composer-keep", "emoji");
          fallbackEmoji.removeAttribute("data-jingepi-composer-overflow");
        }
      }
    }
    tagComposerIconButtons();
  }

  function isNarrowSettingsViewport() {
    try {
      return window.matchMedia("(max-width: 900px)").matches;
    } catch (e) {
      return window.innerWidth <= 900;
    }
  }

  function looksLikeSettingsDialogNode(el) {
    if (!el || !el.classList) return false;
    var cn = String(el.className || "");
    if (/SettingsDialog|UserSettingsDialog|RoomSettingsDialog|SpaceSettingsDialog/.test(cn)) {
      return true;
    }
    if (el.classList.contains("mx_SettingsDialog_content")) return true;
    if (
      el.getAttribute &&
      el.getAttribute("role") === "dialog" &&
      el.querySelector &&
      el.querySelector(".mx_TabbedView, .mx_SettingsTab, .mx_SettingsDialog_content")
    ) {
      return true;
    }
    return false;
  }

  function wrapperContainsSettings(wrapper) {
    if (!wrapper || !wrapper.querySelector) return false;
    if (
      wrapper.querySelector(
        ".mx_UserSettingsDialog, .mx_SettingsDialog, [class*='SettingsDialog'], .mx_SettingsDialog_content"
      )
    ) {
      return true;
    }
    var dialogs = wrapper.querySelectorAll('[role="dialog"], .mx_Dialog_fixedWidth');
    for (var i = 0; i < dialogs.length; i++) {
      if (looksLikeSettingsDialogNode(dialogs[i])) return true;
    }
    return false;
  }

  function applyInlineMaximizedWrapper(el) {
    if (!el || !el.style) return;
    el.setAttribute("data-jingepi-fullscreen-settings", "1");
    var s = el.style;
    s.setProperty("position", "fixed", "important");
    s.setProperty("inset", "0", "important");
    s.setProperty("left", "0", "important");
    s.setProperty("top", "0", "important");
    s.setProperty("right", "0", "important");
    s.setProperty("bottom", "0", "important");
    s.setProperty("width", "100%", "important");
    s.setProperty("height", "100%", "important");
    s.setProperty("max-width", "none", "important");
    s.setProperty("max-height", "none", "important");
    s.setProperty("min-width", "0", "important");
    s.setProperty("margin", "0", "important");
    s.setProperty("padding", "8px", "important");
    s.setProperty("border-radius", "0", "important");
    s.setProperty("transform", "none", "important");
    s.setProperty("box-sizing", "border-box", "important");
    s.setProperty("display", "flex", "important");
    s.setProperty("flex-direction", "column", "important");
    s.setProperty("align-items", "center", "important");
    s.setProperty("justify-content", "center", "important");
    s.setProperty("overflow", "auto", "important");
  }

  function applyInlineBackdrop(el) {
    if (!el || !el.style) return;
    el.setAttribute("data-jingepi-fullscreen-settings", "1");
    var s = el.style;
    s.setProperty("position", "fixed", "important");
    s.setProperty("inset", "0", "important");
    s.setProperty("left", "0", "important");
    s.setProperty("top", "0", "important");
    s.setProperty("right", "0", "important");
    s.setProperty("bottom", "0", "important");
    s.setProperty("width", "100%", "important");
    s.setProperty("height", "100%", "important");
    s.setProperty("max-width", "none", "important");
    s.setProperty("max-height", "none", "important");
    s.setProperty("margin", "0", "important");
    s.setProperty("padding", "0", "important");
    s.setProperty("border-radius", "0", "important");
    s.setProperty("transform", "none", "important");
    s.setProperty("box-sizing", "border-box", "important");
  }

  function applyInlineMaximizedShell(el) {
    if (!el || !el.style) return;
    el.setAttribute("data-jingepi-fullscreen-settings", "1");
    var s = el.style;
    s.setProperty("position", "relative", "important");
    s.setProperty("inset", "auto", "important");
    s.setProperty("left", "auto", "important");
    s.setProperty("top", "auto", "important");
    s.setProperty("right", "auto", "important");
    s.setProperty("bottom", "auto", "important");
    s.setProperty("width", "calc(100vw - 16px)", "important");
    s.setProperty("max-width", "calc(100vw - 16px)", "important");
    s.setProperty("height", "calc(100dvh - 24px)", "important");
    s.setProperty("max-height", "calc(100dvh - 24px)", "important");
    s.setProperty("min-width", "0", "important");
    s.setProperty("min-height", "0", "important");
    s.setProperty("margin", "0 auto", "important");
    s.setProperty("padding", "0", "important");
    s.setProperty("border-radius", "16px", "important");
    s.setProperty("transform", "none", "important");
    s.setProperty("box-sizing", "border-box", "important");
    s.setProperty("overflow-x", "hidden", "important");
    s.setProperty("overflow-y", "hidden", "important");
    s.setProperty("flex", "0 1 auto", "important");
    s.setProperty("align-self", "center", "important");
    s.setProperty("display", "flex", "important");
    s.setProperty("flex-direction", "column", "important");
  }

  function applyInlineFillParent(el) {
    if (!el || !el.style) return;
    el.setAttribute("data-jingepi-fullscreen-settings", "1");
    var s = el.style;
    s.setProperty("position", "relative", "important");
    s.setProperty("inset", "auto", "important");
    s.setProperty("left", "auto", "important");
    s.setProperty("top", "auto", "important");
    s.setProperty("right", "auto", "important");
    s.setProperty("bottom", "auto", "important");
    s.setProperty("width", "100%", "important");
    s.setProperty("height", "100%", "important");
    s.setProperty("max-width", "100%", "important");
    s.setProperty("max-height", "100%", "important");
    s.setProperty("min-width", "0", "important");
    s.setProperty("min-height", "0", "important");
    s.setProperty("margin", "0", "important");
    s.setProperty("padding", "0", "important");
    s.setProperty("border-radius", "0", "important");
    s.setProperty("transform", "none", "important");
    s.setProperty("box-sizing", "border-box", "important");
    s.setProperty("overflow-x", "hidden", "important");
    s.setProperty("flex", "1 1 auto", "important");
    s.setProperty("align-self", "stretch", "important");
    s.setProperty("display", "flex", "important");
    s.setProperty("flex-direction", "column", "important");
  }

  function clearInlineFullscreenMarks(scope) {
    var root = scope || document;
    var marked = root.querySelectorAll
      ? root.querySelectorAll("[data-jingepi-fullscreen-settings='1']")
      : [];
    for (var i = 0; i < marked.length; i++) {
      var el = marked[i];
      el.removeAttribute("data-jingepi-fullscreen-settings");
      if (!el.style) continue;
      [
        "position",
        "inset",
        "left",
        "top",
        "right",
        "bottom",
        "width",
        "height",
        "max-width",
        "max-height",
        "min-width",
        "min-height",
        "margin",
        "padding",
        "border-radius",
        "transform",
        "box-sizing",
        "overflow",
        "overflow-x",
        "overflow-y",
        "flex",
        "align-self",
        "align-items",
        "justify-content",
        "display",
        "flex-direction",
      ].forEach(function (prop) {
        el.style.removeProperty(prop);
      });
    }
  }

  function enforceFullscreenSettingsDialogs() {
    if (!isNarrowSettingsViewport()) {
      clearInlineFullscreenMarks(document);
      return;
    }
    var wrappers = document.querySelectorAll(
      ".mx_Dialog_wrapper, .mx_Dialog_staticWrapper"
    );
    for (var w = 0; w < wrappers.length; w++) {
      var wrapper = wrappers[w];
      if (!wrapperContainsSettings(wrapper)) continue;
      wrapper.setAttribute("data-jingepi-fullscreen-settings", "1");
      applyInlineMaximizedWrapper(wrapper);

      var bg = wrapper.querySelector(".mx_Dialog_background, .mx_Dialog_overlay");
      if (bg) applyInlineBackdrop(bg);

      var border = wrapper.querySelector(":scope > .mx_Dialog_border, .mx_Dialog_border");
      var outerDialog = border
        ? border.querySelector(":scope > .mx_Dialog")
        : wrapper.querySelector(":scope > .mx_Dialog");
      var sizedShell = false;
      if (border) {
        applyInlineMaximizedShell(border);
        sizedShell = true;
      }
      if (outerDialog && !looksLikeSettingsDialogNode(outerDialog)) {
        if (sizedShell) applyInlineFillParent(outerDialog);
        else {
          applyInlineMaximizedShell(outerDialog);
          sizedShell = true;
        }
      }

      var settingsNodes = wrapper.querySelectorAll(
        ".mx_UserSettingsDialog, .mx_SettingsDialog, .mx_RoomSettingsDialog, .mx_SpaceSettingsDialog, .mx_Dialog_fixedWidth[role='dialog']"
      );
      for (var i = 0; i < settingsNodes.length; i++) {
        var node = settingsNodes[i];
        var ncn = String(node.className || "");
        if (/SettingsDialog_content|_content/.test(ncn) && !/UserSettingsDialog|RoomSettingsDialog|SpaceSettingsDialog|^[\w\s-]*SettingsDialog[\w\s-]*$/.test(ncn)) {
          continue;
        }
        if (
          !looksLikeSettingsDialogNode(node) &&
          !/UserSettingsDialog|RoomSettingsDialog|SpaceSettingsDialog|(?:^|\s)mx_SettingsDialog(?:\s|$)/.test(ncn)
        ) {
          continue;
        }
        if (sizedShell) applyInlineFillParent(node);
        else {
          applyInlineMaximizedShell(node);
          sizedShell = true;
        }
        node.style.setProperty("overflow-y", "hidden", "important");
      }

      var contents = wrapper.querySelectorAll(
        ".mx_SettingsDialog_content, .mx_UserSettingsDialog > .mx_Dialog_content, .mx_SettingsDialog > .mx_Dialog_content, .mx_TabbedView_tabPanel, .mx_TabbedView_tabPanelContent"
      );
      for (var c = 0; c < contents.length; c++) {
        var content = contents[c];
        content.setAttribute("data-jingepi-fullscreen-settings", "1");
        content.style.setProperty("position", "relative", "important");
        content.style.setProperty("inset", "auto", "important");
        content.style.setProperty("left", "auto", "important");
        content.style.setProperty("top", "auto", "important");
        content.style.setProperty("right", "auto", "important");
        content.style.setProperty("bottom", "auto", "important");
        content.style.setProperty("width", "100%", "important");
        content.style.setProperty("height", "auto", "important");
        content.style.setProperty("max-width", "100%", "important");
        content.style.setProperty("max-height", "none", "important");
        content.style.setProperty("min-width", "0", "important");
        content.style.setProperty("min-height", "0", "important");
        content.style.setProperty("flex", "1 1 0%", "important");
        content.style.setProperty("display", "flex", "important");
        content.style.setProperty("flex-direction", "column", "important");
        content.style.setProperty("overflow-x", "hidden", "important");
        content.style.setProperty("overflow-y", "hidden", "important");
        content.style.setProperty("box-sizing", "border-box", "important");
        content.style.setProperty("border-radius", "0", "important");
        content.style.setProperty("transform", "none", "important");
        content.style.setProperty("-webkit-overflow-scrolling", "touch");
      }

      var tabbed = wrapper.querySelectorAll(
        ".mx_UserSettingsDialog .mx_TabbedView, .mx_SettingsDialog .mx_TabbedView, .mx_RoomSettingsDialog .mx_TabbedView, .mx_SpaceSettingsDialog .mx_TabbedView"
      );
      for (var t = 0; t < tabbed.length; t++) {
        var tv = tabbed[t];
        tv.setAttribute("data-jingepi-fullscreen-settings", "1");
        tv.style.setProperty("position", "relative", "important");
        tv.style.setProperty("inset", "auto", "important");
        tv.style.setProperty("left", "auto", "important");
        tv.style.setProperty("top", "auto", "important");
        tv.style.setProperty("right", "auto", "important");
        tv.style.setProperty("bottom", "auto", "important");
        tv.style.setProperty("flex", "1 1 0%", "important");
        tv.style.setProperty("min-width", "0", "important");
        tv.style.setProperty("min-height", "0", "important");
        tv.style.setProperty("height", "auto", "important");
        tv.style.setProperty("width", "100%", "important");
        tv.style.setProperty("max-width", "100%", "important");
        tv.style.setProperty("display", "flex", "important");
        tv.style.setProperty("flex-direction", "row", "important");
        tv.style.setProperty("overflow", "hidden", "important");
        tv.style.setProperty("box-sizing", "border-box", "important");
      }

      var toasts = wrapper.querySelectorAll(".mx_SettingsDialog_toastContainer");
      for (var z = 0; z < toasts.length; z++) {
        var toast = toasts[z];
        toast.setAttribute("data-jingepi-fullscreen-settings", "1");
        toast.style.setProperty("position", "absolute", "important");
        toast.style.setProperty("left", "12px", "important");
        toast.style.setProperty("right", "12px", "important");
        toast.style.setProperty("bottom", "12px", "important");
        toast.style.setProperty("top", "auto", "important");
        toast.style.setProperty("width", "auto", "important");
        toast.style.setProperty("height", "auto", "important");
        toast.style.setProperty("max-height", "40%", "important");
        toast.style.setProperty("flex", "0 0 auto", "important");
        toast.style.setProperty("pointer-events", "none", "important");
        toast.style.setProperty("z-index", "6", "important");
      }
    }
  }

  var suppressRunning = false;
  var suppressTimer = 0;
  var obs = null;

  function suppress() {
    if (suppressRunning) return;
    suppressRunning = true;
    /* 断开 observer，避免本轮 DOM 写入立刻回灌成死循环 */
    try {
      if (obs) obs.disconnect();
    } catch (_d0) {
      /* ignore */
    }
    try {
      suppressToasts();
      hideEncryptionTabs();
      hideSectionsByHeading();
      hideRoomEncryptionToggles();
      hideAddServerUi();
      hideThemeSwitcher();
      hideDisplayNameUi();
      hideCreateRoomUi();
      collapseRoomHeaderActions();
      layoutComposerMobile();
      tagComposerIconButtons();
      /* 返回锁期间勿跑侧栏 toggle（会 expand/collapse + 触发大量 mutation） */
      if (!mobileQqBackLock) {
        enhanceLeftPanelToggle();
      }
      syncMobileQqPages();
      syncMobileSpaceBar();
      enforceFullscreenSettingsDialogs();
      forceGoldCssVars(document.documentElement);
      forceGoldCssVars(document.body);
      paintInlineGreens(document);
    } finally {
      suppressRunning = false;
      try {
        if (obs && document.documentElement) {
          obs.observe(document.documentElement, {
            childList: true,
            subtree: true,
          });
        }
      } catch (_d1) {
        /* ignore */
      }
    }
  }

  function scheduleSuppress() {
    if (suppressRunning || suppressTimer) return;
    suppressTimer = setTimeout(function () {
      suppressTimer = 0;
      suppress();
    }, 120);
  }

  obs = new MutationObserver(scheduleSuppress);

  function start() {
    forceJinGeTheme();
    injectCss();
    refreshCreateCapability();
    setInterval(refreshCreateCapability, 30000);
    bindMobileQqNav();
    obs.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
    setInterval(suppress, 1500);
    window.addEventListener("resize", function () {
      enforceFullscreenSettingsDialogs();
      if (mobileQqBackLock) return;
      /* 勿先清 mobileQqLastMode：桌面复位依赖 sync 内 resetDesktopLayoutFromMobile */
      syncMobileQqPages();
      syncMobileSpaceBar();
    });
    try {
      window.matchMedia("(max-width: 900px)").addEventListener("change", function () {
        enforceFullscreenSettingsDialogs();
        if (mobileQqBackLock) return;
        syncMobileQqPages();
        syncMobileSpaceBar();
      });
    } catch (e) {}
    suppress();
    markMobileBodyFlag();
    setTimeout(syncMobileQqPages, 400);
    setTimeout(syncMobileQqPages, 1200);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
