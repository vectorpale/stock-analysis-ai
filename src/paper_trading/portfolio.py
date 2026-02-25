"""
模拟盘组合管理器 - SQLite 存储
管理现金、持仓、交易记录、每日净值快照
"""

import logging
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_DIR = Path("data/paper_trading")
DB_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DB = DB_DIR / "portfolio.db"


class PortfolioManager:
    """SQLite-backed 模拟盘组合管理器"""

    def __init__(self, db_path: str = str(DEFAULT_DB), initial_capital: float = 1_000_000.0):
        self.db_path = db_path
        self.initial_capital = initial_capital
        self._init_db()

    # ==================================================================
    # 数据库初始化
    # ==================================================================
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS portfolio_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    shares REAL NOT NULL DEFAULT 0,
                    avg_cost REAL NOT NULL DEFAULT 0,
                    first_buy_date TEXT,
                    last_update TEXT
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    shares REAL NOT NULL,
                    price REAL NOT NULL,
                    total_amount REAL NOT NULL,
                    commission REAL NOT NULL DEFAULT 0,
                    recommendation TEXT,
                    confidence INTEGER,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS daily_snapshots (
                    date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    shares REAL,
                    price REAL,
                    market_value REAL,
                    PRIMARY KEY (date, symbol)
                );

                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    date TEXT PRIMARY KEY,
                    cash REAL,
                    positions_value REAL,
                    total_value REAL,
                    daily_pnl REAL,
                    total_pnl REAL,
                    total_return_pct REAL
                );

                CREATE TABLE IF NOT EXISTS analysis_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    recommendation TEXT,
                    confidence INTEGER,
                    target_price REAL,
                    stop_loss REAL,
                    position_size_pct REAL,
                    price_at_analysis REAL,
                    executive_summary TEXT,
                    action_taken TEXT,
                    full_result TEXT
                );

                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol TEXT PRIMARY KEY,
                    added_date TEXT,
                    notes TEXT
                );
            """)
            # 初始化元数据
            row = conn.execute(
                "SELECT value FROM portfolio_meta WHERE key='initial_capital'"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO portfolio_meta (key, value) VALUES (?, ?)",
                    ("initial_capital", str(self.initial_capital)),
                )
                conn.execute(
                    "INSERT INTO portfolio_meta (key, value) VALUES (?, ?)",
                    ("cash", str(self.initial_capital)),
                )
                conn.execute(
                    "INSERT INTO portfolio_meta (key, value) VALUES (?, ?)",
                    ("created_at", datetime.now().isoformat()),
                )

    # ==================================================================
    # 元数据
    # ==================================================================
    def _get_meta(self, key: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM portfolio_meta WHERE key=?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def _set_meta(self, key: str, value: str, conn=None):
        if conn:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
        else:
            with self._conn() as c:
                c.execute(
                    "INSERT OR REPLACE INTO portfolio_meta (key, value) VALUES (?, ?)",
                    (key, value),
                )

    @property
    def cash(self) -> float:
        return float(self._get_meta("cash") or self.initial_capital)

    @cash.setter
    def cash(self, value: float):
        self._set_meta("cash", str(value))

    # ==================================================================
    # 自选股
    # ==================================================================
    def set_watchlist(self, symbols: list[str]):
        with self._conn() as conn:
            conn.execute("DELETE FROM watchlist")
            for s in symbols:
                conn.execute(
                    "INSERT INTO watchlist (symbol, added_date) VALUES (?, ?)",
                    (s, datetime.now().isoformat()),
                )

    def get_watchlist(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT symbol FROM watchlist").fetchall()
            return [r["symbol"] for r in rows]

    # ==================================================================
    # 持仓操作
    # ==================================================================
    def get_position(self, symbol: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE symbol=?", (symbol,)
            ).fetchone()
            if row and row["shares"] > 0:
                return dict(row)
            return {"symbol": symbol, "shares": 0, "avg_cost": 0}

    def get_all_positions(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE shares > 0"
            ).fetchall()
            return [dict(r) for r in rows]

    def buy(
        self,
        symbol: str,
        shares: float,
        price: float,
        recommendation: str = "",
        confidence: int = 0,
        reason: str = "",
    ) -> dict:
        """买入股票，返回交易记录"""
        current_cash = self.cash
        total = shares * price
        if total > current_cash:
            # 调整为可用现金能买的最大数量（整数股）
            shares = int(current_cash / price)
            if shares <= 0:
                return {"success": False, "error": "现金不足"}
            total = shares * price

        now = datetime.now().isoformat()
        new_cash = current_cash - total

        with self._conn() as conn:
            # 更新持仓
            existing = conn.execute(
                "SELECT shares, avg_cost FROM positions WHERE symbol=?", (symbol,)
            ).fetchone()

            if existing and existing["shares"] > 0:
                old_shares = existing["shares"]
                old_cost = existing["avg_cost"]
                new_shares = old_shares + shares
                new_cost = (old_shares * old_cost + shares * price) / new_shares
                conn.execute(
                    "UPDATE positions SET shares=?, avg_cost=?, last_update=? WHERE symbol=?",
                    (new_shares, round(new_cost, 4), now, symbol),
                )
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO positions (symbol, shares, avg_cost, first_buy_date, last_update) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (symbol, shares, round(price, 4), now, now),
                )

            # 扣减现金
            self._set_meta("cash", str(new_cash), conn=conn)

            # 记录交易
            conn.execute(
                "INSERT INTO trades (timestamp, symbol, action, shares, price, total_amount, "
                "recommendation, confidence, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, symbol, "BUY", shares, price, total, recommendation, confidence, reason),
            )

        trade = {
            "success": True,
            "action": "BUY",
            "symbol": symbol,
            "shares": shares,
            "price": price,
            "total": total,
            "remaining_cash": new_cash,
        }
        logger.info(f"买入 {symbol}: {shares}股 @ ${price:.2f}, 总额 ${total:,.2f}")
        return trade

    def sell(
        self,
        symbol: str,
        shares: float,
        price: float,
        recommendation: str = "",
        confidence: int = 0,
        reason: str = "",
    ) -> dict:
        """卖出股票"""
        pos = self.get_position(symbol)
        if pos["shares"] <= 0:
            return {"success": False, "error": f"无 {symbol} 持仓"}

        shares = min(shares, pos["shares"])
        total = shares * price
        now = datetime.now().isoformat()
        current_cash = self.cash
        new_cash = current_cash + total

        with self._conn() as conn:
            remaining = pos["shares"] - shares
            if remaining <= 0:
                conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            else:
                conn.execute(
                    "UPDATE positions SET shares=?, last_update=? WHERE symbol=?",
                    (remaining, now, symbol),
                )

            self._set_meta("cash", str(new_cash), conn=conn)

            pnl = (price - pos["avg_cost"]) * shares
            conn.execute(
                "INSERT INTO trades (timestamp, symbol, action, shares, price, total_amount, "
                "recommendation, confidence, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, symbol, "SELL", shares, price, total, recommendation, confidence,
                 f"{reason} | PnL: ${pnl:+,.2f}"),
            )

        trade = {
            "success": True,
            "action": "SELL",
            "symbol": symbol,
            "shares": shares,
            "price": price,
            "total": total,
            "pnl": pnl,
            "remaining_cash": new_cash,
        }
        logger.info(f"卖出 {symbol}: {shares}股 @ ${price:.2f}, PnL: ${pnl:+,.2f}")
        return trade

    # ==================================================================
    # 快照与统计
    # ==================================================================
    def take_snapshot(self, prices: dict[str, float]):
        """记录每日组合快照（传入各股当前价格）"""
        today = date.today().isoformat()
        positions = self.get_all_positions()
        positions_value = 0.0

        with self._conn() as conn:
            for pos in positions:
                sym = pos["symbol"]
                price = prices.get(sym, 0)
                mv = pos["shares"] * price
                positions_value += mv
                conn.execute(
                    "INSERT OR REPLACE INTO daily_snapshots (date, symbol, shares, price, market_value) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (today, sym, pos["shares"], price, mv),
                )

            total_value = self.cash + positions_value
            initial = float(self._get_meta("initial_capital") or self.initial_capital)

            # 计算日收益
            prev = conn.execute(
                "SELECT total_value FROM portfolio_snapshots ORDER BY date DESC LIMIT 1"
            ).fetchone()
            prev_value = prev["total_value"] if prev else initial
            daily_pnl = total_value - prev_value
            total_pnl = total_value - initial
            total_return = (total_value / initial - 1) * 100

            conn.execute(
                "INSERT OR REPLACE INTO portfolio_snapshots "
                "(date, cash, positions_value, total_value, daily_pnl, total_pnl, total_return_pct) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (today, self.cash, positions_value, total_value, daily_pnl, total_pnl, round(total_return, 4)),
            )

        logger.info(f"快照 {today}: 总值 ${total_value:,.2f}, 日PnL ${daily_pnl:+,.2f}")

    def get_portfolio_value(self, prices: dict[str, float]) -> dict:
        """计算当前组合总值"""
        positions = self.get_all_positions()
        positions_value = 0.0
        position_details = []

        for pos in positions:
            sym = pos["symbol"]
            price = prices.get(sym, 0)
            mv = pos["shares"] * price
            pnl = (price - pos["avg_cost"]) * pos["shares"]
            pnl_pct = (price / pos["avg_cost"] - 1) * 100 if pos["avg_cost"] > 0 else 0
            positions_value += mv
            position_details.append({
                "symbol": sym,
                "shares": pos["shares"],
                "avg_cost": pos["avg_cost"],
                "current_price": price,
                "market_value": mv,
                "unrealized_pnl": pnl,
                "pnl_pct": round(pnl_pct, 2),
            })

        total_value = self.cash + positions_value
        initial = float(self._get_meta("initial_capital") or self.initial_capital)
        return {
            "cash": self.cash,
            "positions_value": positions_value,
            "total_value": total_value,
            "total_pnl": total_value - initial,
            "total_return_pct": round((total_value / initial - 1) * 100, 4),
            "positions": position_details,
        }

    def get_trade_history(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_snapshots(self, limit: int = 365) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM portfolio_snapshots ORDER BY date ASC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_analysis_log(self, symbol: str = None, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM analysis_log WHERE symbol=? ORDER BY timestamp DESC LIMIT ?",
                    (symbol, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM analysis_log ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def log_analysis(self, symbol: str, result: dict, action_taken: str = ""):
        """记录分析结果"""
        cio = result.get("phases", {}).get("cio_decision", {})
        import json
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO analysis_log "
                "(timestamp, symbol, recommendation, confidence, target_price, stop_loss, "
                "position_size_pct, price_at_analysis, executive_summary, action_taken, full_result) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(),
                    symbol,
                    cio.get("recommendation"),
                    cio.get("confidence"),
                    cio.get("target_price"),
                    cio.get("stop_loss"),
                    cio.get("position_size_pct"),
                    cio.get("price_at_analysis"),
                    cio.get("executive_summary", "")[:500],
                    action_taken,
                    json.dumps(result, ensure_ascii=False, default=str)[:10000],
                ),
            )

    # ==================================================================
    # 绩效统计
    # ==================================================================
    def get_performance_stats(self) -> dict:
        """计算组合绩效指标"""
        with self._conn() as conn:
            # 已平仓交易
            sells = conn.execute(
                "SELECT * FROM trades WHERE action='SELL' ORDER BY timestamp"
            ).fetchall()

            if not sells:
                return {
                    "total_trades": 0,
                    "win_rate": 0,
                    "avg_win": 0,
                    "avg_loss": 0,
                    "profit_factor": 0,
                    "max_drawdown_pct": 0,
                }

            wins = []
            losses = []
            for s in sells:
                reason = s["reason"] or ""
                if "PnL:" in reason:
                    pnl_str = reason.split("PnL:")[1].strip().replace("$", "").replace(",", "").replace("+", "")
                    try:
                        pnl = float(pnl_str)
                        if pnl >= 0:
                            wins.append(pnl)
                        else:
                            losses.append(pnl)
                    except ValueError:
                        pass

            total = len(wins) + len(losses)
            win_rate = len(wins) / total * 100 if total > 0 else 0
            avg_win = sum(wins) / len(wins) if wins else 0
            avg_loss = sum(losses) / len(losses) if losses else 0
            profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float('inf')

            # 最大回撤
            snapshots = conn.execute(
                "SELECT total_value FROM portfolio_snapshots ORDER BY date"
            ).fetchall()
            max_dd = 0.0
            peak = 0.0
            for snap in snapshots:
                v = snap["total_value"]
                if v > peak:
                    peak = v
                dd = (peak - v) / peak * 100 if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd

            return {
                "total_trades": len(sells),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(win_rate, 1),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "profit_factor": round(profit_factor, 2),
                "max_drawdown_pct": round(max_dd, 2),
                "total_realized_pnl": round(sum(wins) + sum(losses), 2),
            }

    def reset(self):
        """重置模拟盘（清空所有数据）"""
        with self._conn() as conn:
            conn.executescript("""
                DELETE FROM positions;
                DELETE FROM trades;
                DELETE FROM daily_snapshots;
                DELETE FROM portfolio_snapshots;
                DELETE FROM analysis_log;
            """)
            self._set_meta("cash", str(self.initial_capital))
        logger.info("模拟盘已重置")
