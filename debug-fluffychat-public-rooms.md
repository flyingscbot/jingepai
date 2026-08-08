# Debug Session: fluffychat-public-rooms

## Status
[OPEN]

## Symptom
- 主界面能看到已加入的公开房间列表。
- 进入 FluffyChat "添加到对话" → "公开聊天室" 标签后，列表为空或提示失败。
- 之前已修复：退出登录时 Matrix 会话同步注销、管理员创建房间自动公开、代理修复 publicRooms 响应字段。

## Environment
- OS: Windows 11
- Flask proxy: http://127.0.0.1:1000
- Synapse: http://127.0.0.1:8008
- Client: FluffyChat Web (iframe in main app)

## Hypotheses
1. H1: 代理对 publicRooms 响应的后处理在浏览器真实请求时未生效。
2. H2: FluffyChat 发送了带 server 参数或其他过滤条件的 publicRooms 请求，代理处理遗漏。
3. H3: FluffyChat UI 渲染依赖未注入的字段导致显示为空。
4. H4: publicRooms 返回的房间缺少 canonical_alias，FluffyChat 只显示带别名房间。
5. H5: 创建房间时的后处理逻辑在某些路径下失败。

## Evidence Log
- TBD

## Fix
- TBD

## Verification
- TBD
