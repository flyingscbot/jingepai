# 沙盘项目合并到 JINGEPI + 账户系统对接

## Context
将独立的"模拟沙盘"项目（股票/基金模拟交易）合并到 JINGEPI 主项目中，并让沙盘模块使用 JINGEPI 的账户系统（SQLite `users.db`），替代沙盘原有的 JSON 文件认证。暂时不原网页中添加沙盘入口，沙盘页面通过直接 URL 访问。

## 当前状态

### 沙盘项目（源）
- 位置：`c:\Users\kongl\Desktop\沙盘\沙盘\`
- 核心模块：`sandbox/` 目录（`__init__.py`, `db.py`, `routes.py`, `trade.py`, `market_data.py`, `permissions.py`, `seed.py`, `akshare_cols.py`）
- 数据文件：`sandbox/_real_stocks.csv`, `sandbox/_real_funds.csv`
- 模板：`templates/` 下 8 个文件（`_sandbox_base.html`, `main.html`, `market.html`, `detail.html`, `portfolio.html`, `admin.html`, `login.html`, `register.html`）
- 数据库：`sandbox.db`（SQLite，SQLAlchemy ORM）
- 认证：`user_db.json`（JSON 文件，明文密码）
- 沙盘角色：normal, vip, intern_teacher, teacher, senior_teacher, admin

### JINGEPI 项目（目标）
- 位置：`c:\Users\kongl\Documents\JINGEPI\`
- 认证系统：`users.db`（SQLite，Werkzeug scrypt 哈希），通过 `user_db.py` 管理
- 角色：super_admin, admin, specialist, user
- Session 字段：`user_id`, `username`, `is_login`, `role`
- 已有 `market_data.py`（MBTI 分析用，与沙盘的不同）

## 角色映射
沙盘角色 → JINGEPI 角色：
| 沙盘角色 | JINGEPI 角色 |
|---------|-------------|
| admin | super_admin |
| senior_teacher | admin |
| teacher | admin |
| intern_teacher | specialist |
| vip | user |
| normal | user |

沙盘内部权限通过沙盘自身的 `permissions.py` 角色矩阵控制，JINGEPI 角色仅用于初始映射。

## 实施步骤

### 步骤 1：复制沙盘模块代码到 JINGEPI
将以下文件/目录复制到 JINGEPI 项目：

1. **Python 模块**：`sandbox/` 整个目录 → `c:\Users\kongl\Documents\JINGEPI\sandbox\`
   - 排除 `__pycache__/` 目录
   - 包含：`__init__.py`, `db.py`, `routes.py`, `trade.py`, `market_data.py`, `permissions.py`, `seed.py`, `akshare_cols.py`
   - 包含数据文件：`_real_stocks.csv`, `_real_funds.csv`

2. **模板文件**：复制到 `c:\Users\kongl\Documents\JINGEPI\templates\sandbox\`
   - `_sandbox_base.html`, `main.html`, `market.html`, `detail.html`, `portfolio.html`, `admin.html`
   - 不复制 `login.html` 和 `register.html`（沙盘将使用 JINGEPI 的登录/注册）

### 步骤 2：修改 `sandbox/db.py` - 账户系统对接
核心改动：让 `sync_user_from_session` 从 JINGEPI 的 `users.db` 读取用户，而非 `user_db.json`。

改动点：
- 删除 `_read_json_user` 函数和 `JSON_DB_FILE` 常量
- 导入 JINGEPI 的 `user_db` 模块
- 修改 `sync_user_from_session`：
  - 从 `session` 读取 `user_id`、`username`、`is_login`
  - 调用 `user_db.get_user_by_id(user_id)` 获取 JINGEPI 用户
  - 角色映射：`_map_jingepi_role_to_sandbox()` 函数
  - 如果沙盘 User 表不存在该用户则创建
- 修改 `DB_PATH`：使用 JINGEPI 的 BASE_DIR（沙盘数据库文件放在 JINGEPI 根目录）

### 步骤 3：修改 `sandbox/permissions.py` - 角色标签
- 更新 `ROLE_LABELS` 以匹配映射后的角色
- `get_current_user` 和 `permission_required` 保持不变（它们依赖 `sync_user_from_session`）

### 步骤 4：修改 `sandbox/__init__.py` - 蓝图配置
- 调整模板文件夹路径，指向 `templates/sandbox/`
- 设置 `template_folder` 参数

### 步骤 5：修改 `sandbox/routes.py` - 模板路径
- 所有 `render_template` 调用改为 `render_template('sandbox/xxx.html', ...)`
- 移除 `login.html` 和 `register.html` 相关路由（沙盘不再有自己的登录页）
- 未登录时重定向到 JINGEPI 的登录页：`redirect(url_for('home.index', modal='login'))`

### 步骤 6：在 JINGEPI `main.py` 中注册沙盘蓝图
- 在 `main.py` 中添加沙盘蓝图导入和注册
- 沙盘初始化（`init_db` + `start_scheduler`）加入启动流程
- 使用 `WERKZEUG_RUN_MAIN` 守卫避免 reloader 重复初始化

### 步骤 7：更新依赖
- 在 JINGEPI 的 `requirements.txt` 中添加：
  - `Flask-SQLAlchemy>=3.1`
  - `SQLAlchemy>=2.0`
  - `APScheduler>=3.10`

### 步骤 8：不添加网页入口
- 不修改 `templates/base.html`、`templates/home/index.html` 或任何现有模板
- 沙盘页面通过直接 URL 访问（如 `/market`, `/portfolio`, `/admin`）

## 关键文件清单
- **新建**：`sandbox/` 目录（从沙盘项目复制）
- **新建**：`templates/sandbox/` 目录（从沙盘项目复制模板）
- **修改**：`sandbox/db.py` — 账户系统对接
- **修改**：`sandbox/permissions.py` — 角色标签更新
- **修改**：`sandbox/__init__.py` — 模板路径配置
- **修改**：`sandbox/routes.py` — 模板路径 + 登录重定向
- **修改**：`main.py` — 注册沙盘蓝图
- **修改**：`requirements.txt` — 添加依赖

## 验证
1. 启动 Flask：`venv\Scripts\python.exe main.py`
2. 在浏览器访问 JINGEPI 首页，正常登录
3. 登录后直接访问 `http://127.0.0.1:1000/market` — 应显示沙盘行情页面
4. 访问 `http://127.0.0.1:1000/portfolio` — 应显示持仓页面
5. 访问 `http://127.0.0.1:1000/admin` — 管理员应能访问管理后台
6. 未登录时访问沙盘页面应重定向到 JINGEPI 登录页
7. JINGEPI 首页不显示任何沙盘入口链接
8. 检查沙盘数据库 `sandbox.db` 是否正确创建在 JINGEPI 根目录