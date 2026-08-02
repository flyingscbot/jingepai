from flask import Flask, request, jsonify, session, redirect, url_for, render_template
from functools import wraps
import datetime
import json
import os

from home import home_bp

app = Flask(__name__)
app.secret_key = "train_2026_abc123"
app.permanent_session_lifetime = datetime.timedelta(hours=2)

app.register_blueprint(home_bp)


@app.context_processor
def inject_user():
    """所有模板共享登录状态与用户名，方便统一主题布局。"""
    return {
        "is_login": bool(session.get("is_login")),
        "username": session.get("username", ""),
    }


# 登录校验装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_login'):
            return redirect(url_for('home.index', modal='login'))
        return f(*args, **kwargs)
    return decorated_function

DB_FILE = "user_db.json"


def reset_user_db():
    """
    强制生成完整用户数据，每次运行覆盖写入。
    用于初始化或重置数据库。
    """
    data = {
        "user_list": [
            {"id": 1, "username": "张三", "password": "123456", "role": "student"},
            {"id": 2, "username": "李四", "password": "123456", "role": "student"},
            {"id": 3, "username": "王五", "password": "123456", "role": "student"},
            {"id": 4, "username": "赵六", "password": "123456", "role": "student"}
        ]
    }

    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            # ensure_ascii=False 保证中文正常显示，indent=4 保证格式美观
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"✅ 数据库已重置并保存至: {os.path.abspath(DB_FILE)}")
        return True
    except Exception as e:
        print(f"❌ 重置数据库失败: {e}")
        return False


def load_all_users():
    """
    读取所有用户列表。
    具备自动容错机制：如果文件不存在或损坏，会自动尝试重置。
    """
    # 1. 检查文件是否存在
    if not os.path.exists(DB_FILE):
        print("⚠️ 检测到数据库文件不存在，正在自动初始化...")
        if not reset_user_db():
            return []

    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()

            # 2. 检查文件是否为空
            if not content:
                raise ValueError("数据库文件内容为空")

            data = json.loads(content)

            # 3. 验证数据结构
            if isinstance(data, dict) and "user_list" in data:
                user_list = data["user_list"]
                if isinstance(user_list, list):
                    return user_list
                else:
                    raise TypeError("'user_list' 字段不是列表类型")
            else:
                raise KeyError("JSON 结构中缺少 'user_list' 键")

    except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
        print(f"⚠️ 数据库文件损坏或格式错误: {e}")
        print("🔄 正在尝试修复（重新生成数据库）...")
        if reset_user_db():
            # 修复成功后，递归调用自己重新读取最新数据
            return load_all_users()
        else:
            return []
    except Exception as e:
        print(f"❌ 读取数据库时发生未知错误: {e}")
        return []


def get_user_by_name(username):
    """
    根据用户名查找用户。
    返回用户字典，如果未找到则返回 None。
    """
    user_list = load_all_users()

    # 调试信息：显示当前加载状态
    if not user_list:
        print("[DEBUG] 警告：用户列表为空，无法进行查询。")
        return None

    # 遍历查找
    for u in user_list:
        # 使用 .get() 防止键不存在报错，并去除两端空格进行匹配
        db_name = u.get("username", "")
        if db_name.strip() == username.strip():
            return u

    # 未找到时的调试提示
    all_names = [u.get("username", "Unknown") for u in user_list]
    print(f"[DEBUG] 未找到用户 '{username}'。当前库中有: {all_names}")

    return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "GET":
        return redirect(url_for('home.index', modal='login'))
    if not request.is_json:
        return jsonify({"success": False, "message": "请提交JSON数据"})
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"success": False, "message": "账号密码不能为空"})
    user = get_user_by_name(username)
    if user and user["password"] == password:
        session["is_login"] = True
        session["username"] = username
        session.permanent = True
        return jsonify({"success": True, "message": "登录成功"})
    else:
        return jsonify({"success": False, "message": "用户名或密码错误"})

# 主页
@app.route('/main')
@login_required
def main():
    return render_template("main.html")


@app.route('/mbti')
@login_required
def mbti():
    return render_template("mbti.html")


@app.route('/trade')
@login_required
def trade():
    return render_template("trade.html")


@app.route('/chat')
@login_required
def chat():
    return render_template("chat.html")


# 退出登录
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home.index'))


@app.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "GET":
        return redirect(url_for('home.index', modal='register'))

    # POST 处理注册提交
    if not request.is_json:
        return jsonify({"success": False, "message": "请提交JSON数据"})
    data = request.get_json()
    un = data.get("username")
    pw = data.get("password")
    if not un or not pw:
        return jsonify({"success": False, "message": "账号密码不能为空"})

    user_list = load_all_users()
    for u in user_list:
        if u["username"] == un:
            return jsonify({"success": False, "message": "该账号已存在"})

    new_id = max(item["id"] for item in user_list) + 1
    new_user = {
        "id": new_id,
        "username": un,
        "password": pw,
        "role": "student"
    }
    user_list.append(new_user)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump({"user_list": user_list}, f, indent=4, ensure_ascii=False)
    return jsonify({"success": True, "message": "注册成功"})


if __name__ == '__main__':
    app.run(host="127.0.0.1", port=1000, debug=True)