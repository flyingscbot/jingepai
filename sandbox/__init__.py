"""模拟沙盘模式：股票/基金模拟交易沙盘。

作为 Flask Blueprint 挂入 JINGEPI 主应用，使用 JINGEPI 账户系统（users.db）。
模板位于 templates/sandbox/ 目录。
"""
from flask import Blueprint

# 沙盘蓝图（url_prefix=/sandbox，避免与 JINGEPI 主路由冲突）
# 模板通过 render_template('sandbox/xxx.html') 引用
sandbox_bp = Blueprint("sandbox", __name__, url_prefix="/sandbox")


def create_blueprint():
    """返回沙盘蓝图。路由在 routes.py 中注册到本蓝图。"""
    # 延迟导入，避免循环依赖
    from . import routes  # noqa: F401  注册路由
    return sandbox_bp
