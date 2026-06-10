import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional


@dataclass(frozen=True)
class WatchItem:
    id: int
    user_id: int
    ticker: str
    strike: float
    option_type: str
    expiry: str
    price_change: float
    percent_change: float
    last_price: Optional[float]
    last_percent_change: Optional[float]
    created_at: str


class WatchlistStore:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    strike REAL NOT NULL,
                    option_type TEXT NOT NULL CHECK(option_type IN ('call', 'put')),
                    expiry TEXT NOT NULL,
                    price_change REAL NOT NULL,
                    percent_change REAL NOT NULL,
                    last_price REAL,
                    last_percent_change REAL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, ticker, strike, option_type, expiry)
                )
                """
            )

    def add_watch(
        self,
        user_id: int,
        ticker: str,
        strike: float,
        option_type: str,
        expiry: str,
        price_change: float,
        percent_change: float,
    ) -> WatchItem:
        now = datetime.now(timezone.utc).isoformat()
        normalized_ticker = ticker.upper().strip()
        normalized_type = option_type.lower().strip()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO watchlist (
                    user_id, ticker, strike, option_type, expiry,
                    price_change, percent_change, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, ticker, strike, option_type, expiry)
                DO UPDATE SET
                    price_change = excluded.price_change,
                    percent_change = excluded.percent_change
                RETURNING *
                """,
                (
                    user_id,
                    normalized_ticker,
                    strike,
                    normalized_type,
                    expiry,
                    price_change,
                    percent_change,
                    now,
                ),
            )
            return self._row_to_item(cursor.fetchone())

    def list_watches(self, user_id: Optional[int] = None) -> list[WatchItem]:
        with self._connect() as connection:
            if user_id is None:
                rows = connection.execute("SELECT * FROM watchlist ORDER BY ticker, expiry, strike").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM watchlist WHERE user_id = ? ORDER BY ticker, expiry, strike",
                    (user_id,),
                ).fetchall()
            return [self._row_to_item(row) for row in rows]

    def remove_watch(self, user_id: int, watch_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM watchlist WHERE id = ? AND user_id = ?",
                (watch_id, user_id),
            )
            return cursor.rowcount > 0

    def update_snapshot(self, watch_id: int, price: float, percent_change: float) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE watchlist
                SET last_price = ?, last_percent_change = ?
                WHERE id = ?
                """,
                (price, percent_change, watch_id),
            )

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> WatchItem:
        return WatchItem(
            id=row["id"],
            user_id=row["user_id"],
            ticker=row["ticker"],
            strike=row["strike"],
            option_type=row["option_type"],
            expiry=row["expiry"],
            price_change=row["price_change"],
            percent_change=row["percent_change"],
            last_price=row["last_price"],
            last_percent_change=row["last_percent_change"],
            created_at=row["created_at"],
        )
