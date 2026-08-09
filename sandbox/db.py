"""沙盘数据库：SQLAlchemy + SQLite。

用户登录时从 JINGEPI 的 users.db 同步到本表（role 由 JINGEPI 角色映射，capital 由沙盘管理）。
所有货币用 Numeric/Decimal，避免浮点漂移。
"""
import os
import sys
from datetime import datetime, date
from decimal import Decimal

# 确保 JINGEPI 根目录在 sys.path 中，以便导入 user_db
_JINGEPI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _JINGEPI_ROOT not in sys.path:
    sys.path.insert(0, _JINGEPI_ROOT)

from sqlalchemy import (
    create_engine, Column, Integer, String, Numeric, Boolean, DateTime,
    Date, ForeignKey, Text, UniqueConstraint, Index, event,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship

import user_db as _jingepi_users

# ---------------------------------------------------------------------- 引擎
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sandbox.db")
ENGINE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    ENGINE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    """开启 WAL + busy_timeout，提升并发读写。"""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("PRAGMA busy_timeout=60000;")  # 60s 锁等待
    cur.close()


# ---------------------------------------------------------------------- 模型
INITIAL_CAPITAL = Decimal("10000.00")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(String(64), primary_key=True)          # 与 JINGEPI users.db 中 UUID 一致
    username = Column(String(64), unique=True, index=True, nullable=False)
    role = Column(String(32), nullable=False, default="user")  # trial/user/specialist/admin/super_admin
    cash = Column(Numeric(18, 2), nullable=False, default=INITIAL_CAPITAL)
    initial_capital = Column(Numeric(18, 2), nullable=False, default=INITIAL_CAPITAL)
    disabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.now)

    holdings = relationship("Holding", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="user", cascade="all, delete-orphan")


class Stock(Base):
    """自选股票实时缓存（code 为 PK）。"""
    __tablename__ = "stocks"
    code = Column(String(16), primary_key=True)
    name = Column(String(64))
    price = Column(Numeric(12, 4))
    pct_chg = Column(Numeric(8, 4))
    chg = Column(Numeric(12, 4))
    open = Column(Numeric(12, 4))
    high = Column(Numeric(12, 4))
    low = Column(Numeric(12, 4))
    pre_close = Column(Numeric(12, 4))
    volume = Column(Numeric(20, 2))
    amount = Column(Numeric(20, 2))
    turnover = Column(Numeric(8, 4))
    pe = Column(Numeric(12, 4))
    pb = Column(Numeric(12, 4))
    total_mv = Column(Numeric(20, 2))
    circ_mv = Column(Numeric(20, 2))
    updated_at = Column(DateTime, default=datetime.now)
    stale = Column(Boolean, nullable=False, default=False)


class Fund(Base):
    """自选基金实时缓存（code 为 PK）。"""
    __tablename__ = "funds"
    code = Column(String(16), primary_key=True)
    name = Column(String(128))
    unit_nav = Column(Numeric(12, 4))    # 最新公布单位净值
    acc_nav = Column(Numeric(12, 4))     # 累计净值
    est_nav = Column(Numeric(12, 4))     # 盘中估算净值
    est_pct = Column(Numeric(8, 4))      # 估算增长率
    fund_type = Column(String(32))
    nav_date = Column(Date)
    updated_at = Column(DateTime, default=datetime.now)
    stale = Column(Boolean, nullable=False, default=False)


class PriceHistory(Base):
    """近半年日K缓存（股票+基金共用）。"""
    __tablename__ = "price_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(8), nullable=False)   # stock | fund
    code = Column(String(16), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    open = Column(Numeric(12, 4))
    close = Column(Numeric(12, 4))
    high = Column(Numeric(12, 4))
    low = Column(Numeric(12, 4))
    volume = Column(Numeric(20, 2))
    pct_chg = Column(Numeric(8, 4))
    refreshed_at = Column(DateTime, default=datetime.now)
    UniqueConstraint("kind", "code", "date", name="uq_price_history")


class Holding(Base):
    __tablename__ = "holdings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(8), nullable=False)        # stock | fund
    code = Column(String(16), nullable=False, index=True)
    name = Column(String(128))
    total_shares = Column(Numeric(18, 4), nullable=False, default=0)
    available_shares = Column(Numeric(18, 4), nullable=False, default=0)
    frozen_shares = Column(Numeric(18, 4), nullable=False, default=0)  # T+1 冻结
    avg_cost = Column(Numeric(12, 4), nullable=False, default=0)        # 含费用加权成本
    first_buy_at = Column(DateTime)                                      # 最早建仓时间(算持有天数)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    UniqueConstraint("user_id", "kind", "code", name="uq_holding")

    user = relationship("User", back_populates="holdings")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(8), nullable=False)         # stock | fund
    side = Column(String(16), nullable=False)       # buy|sell|subscribe|redeem
    code = Column(String(16), nullable=False)
    name = Column(String(128))
    shares = Column(Numeric(18, 4), nullable=False)
    price = Column(Numeric(12, 4), nullable=False)   # 成交/确认价
    amount = Column(Numeric(18, 2), nullable=False) # 本金
    fee = Column(Numeric(18, 2), nullable=False, default=0)
    stamp_duty = Column(Numeric(18, 2), nullable=False, default=0)
    status = Column(String(16), nullable=False, default="filled")  # pending|filled|settled|cancelled|rejected
    submit_at = Column(DateTime, default=datetime.now)
    confirm_at = Column(DateTime)
    note = Column(String(255))
    related_order_id = Column(Integer)

    user = relationship("User", back_populates="orders")


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(8), nullable=False)        # stock | fund
    code = Column(String(16), nullable=False, index=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False)
    username = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False, default="normal")  # 冗余：徽章显示
    content = Column(String(500), nullable=False)
    parent_id = Column(Integer, ForeignKey("comments.id"), nullable=True)
    status = Column(String(16), nullable=False, default="visible")  # visible|hidden|deleted
    featured = Column(Boolean, nullable=False, default=False)       # 置顶
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="comments")
    replies = relationship("Comment", backref="parent", remote_side=[id])


class Watchlist(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(8), nullable=False)   # stock | fund
    code = Column(String(16), nullable=False)
    name = Column(String(128))
    added_at = Column(DateTime, default=datetime.now)
    added_by = Column(String(64))
    UniqueConstraint("kind", "code", name="uq_watchlist")


class CommentModerationLog(Base):
    __tablename__ = "comment_moderation_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    comment_id = Column(Integer, ForeignKey("comments.id"), nullable=False)
    moderator_id = Column(String(64), nullable=False)
    action = Column(String(16), nullable=False)  # hide|delete|feature|restore
    reason = Column(String(255))
    at = Column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------- 角色
# 沙盘角色与 JINGEPI users.db 角色名一致，直接透传，无需映射。
# JINGEPI: super_admin / admin / specialist / user
# 沙盘额外: trial（沙盘内部分配，JINGEPI 中无对应）


def _sandbox_role_from_jingepi(jingepi_role: str) -> str:
    """从 JINGEPI 角色获取沙盘角色名（直接透传，不转换）。"""
    valid = {"super_admin", "admin", "specialist", "user", "trial"}
    return jingepi_role if jingepi_role in valid else "user"


# ---------------------------------------------------------------------- 工具
def get_session():
    """返回新的 DB session。调用方负责关闭（推荐 `with get_session() as s:`）。"""
    return SessionLocal()


def sync_user_from_session(session, flask_session):
    """根据 JINGEPI flask session 同步用户到沙盘表。

    从 JINGEPI 的 users.db 读取用户信息，创建/更新沙盘 User 记录。
    返回 (User, error_msg)。error_msg 非空表示未登录或找不到用户。
    """
    username = flask_session.get("username")
    user_id = flask_session.get("user_id")
    if not username or not user_id or not flask_session.get("is_login"):
        return None, "未登录"

    s = session
    # 用 JINGEPI UUID 查找沙盘用户（user_id 即 JINGEPI users.db 的 UUID）
    user = s.query(User).filter(User.id == user_id).first()
    if user is None:
        # 从 JINGEPI users.db 获取用户信息
        ju = _jingepi_users.get_user_by_id(user_id)
        if ju is None:
            return None, "用户不存在"
        sandbox_role = _sandbox_role_from_jingepi(ju.get("role", "user"))
        user = User(
            id=ju.get("id", user_id),
            username=username,
            role=sandbox_role,
            cash=INITIAL_CAPITAL,
            initial_capital=INITIAL_CAPITAL,
            disabled=not ju.get("is_active", True),
        )
        s.add(user)
        s.commit()
        s.refresh(user)
    else:
        # 已存在：同步 JINGEPI 最新状态（角色、启停用、用户名）
        ju = _jingepi_users.get_user_by_id(user_id)
        if ju:
            sandbox_role = _sandbox_role_from_jingepi(ju.get("role", "user"))
            is_active = ju.get("is_active", True)
            needs_update = False
            if user.username != username:
                user.username = username
                needs_update = True
            if user.role != sandbox_role:
                user.role = sandbox_role
                needs_update = True
            if user.disabled != (not is_active):
                user.disabled = not is_active
                needs_update = True
            if needs_update:
                s.commit()
                s.refresh(user)
    return user, None


def init_db(app):
    """建表 + 必要时 seed。在 reloader 主子进程调用以免重复。"""
    Base.metadata.create_all(engine)
    # 延迟导入 seed，避免循环
    from . import seed
    seed.ensure_seed()
    app.logger.info("[sandbox] 数据库初始化完成: %s", DB_PATH)
