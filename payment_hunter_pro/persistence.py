"""Persistencia simple con SQLite para resultados e historial."""
import sqlite3
import os
from typing import List
from .models import SearchResult

DB_PATH = "payment_hunter_results.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            gateways TEXT,
            real_form TEXT,
            timestamp TEXT,
            country TEXT,
            confidence_score INTEGER,
            dork TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_result(result: SearchResult):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('''
            INSERT OR IGNORE INTO results (url, gateways, real_form, timestamp, country, confidence_score, dork)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (result.url, result.gateways, result.real_form, result.timestamp, 
              result.country, result.confidence_score, result.dork))
        conn.commit()
    except Exception as e:
        print(f"DB save error: {e}")
    finally:
        conn.close()

def load_all_results() -> List[SearchResult]:
    """Carga solo los resultados positivos (los que tenían formulario de pago)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT url, gateways, real_form, timestamp, country, confidence_score, dork FROM results WHERE real_form = 'Sí' ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return [
        SearchResult(
            url=r[0], gateways=r[1], real_form=r[2], timestamp=r[3],
            country=r[4], confidence_score=r[5], dork=r[6]
        ) for r in rows
    ]

def clear_history():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM results')
    conn.commit()
    conn.close()

def is_url_processed(url: str) -> bool:
    """Returns True if this URL was already analyzed (positive or negative)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('SELECT 1 FROM results WHERE url = ? LIMIT 1', (url,))
        return c.fetchone() is not None
    except Exception:
        return False
    finally:
        conn.close()

def mark_url_processed(url: str, had_payment: bool = False, gateways: str = "", score: int = 0, dork: str = "", country: str = "Global"):
    """Mark a URL as processed. Use for both positive and negative results to avoid re-checking."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        real_form = "Sí" if had_payment else "No"
        timestamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute('''
            INSERT OR IGNORE INTO results 
            (url, gateways, real_form, timestamp, country, confidence_score, dork)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (url, gateways, real_form, timestamp, country, score, dork))
        conn.commit()
    except Exception as e:
        print(f"DB mark error: {e}")
    finally:
        conn.close()
