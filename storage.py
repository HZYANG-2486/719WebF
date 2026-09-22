# -*- coding: utf-8 -*-
"""
719WebF 存储层（SQLite）

用 SQLite 取代原先的 JSON 文件（chat_data.json / temp_files.json），
提供更专业、支持并发与原子操作的持久化方式，并允许通过 db_tool.py
在本地直接查询/修改数据（服务停止时运行）。

设计要点：
- 本模块独立，不 import app，避免循环依赖；由 app.py 调用并传入内存结构。
- 单一连接 + 线程锁，保证多线程（waitress/gevent）下的安全。
- 名称保持与 app.py 原有 load/save 函数对应，便于替换。
"""

import os
import json
import time
import sqlite3
import threading

_LOCK = threading.RLock()
_CONN = None
_DB_PATH = None


# ===================== 连接与建表 =====================
def _connect():
    global _CONN
    if _CONN is None:
        raise RuntimeError("storage 未初始化，请先调用 storage.init(db_path)")
    return _CONN


def init(db_path):
    """初始化数据库：建立连接与表结构。可重复调用（幂等）。"""
    global _CONN, _DB_PATH
    with _LOCK:
        db_path = os.path.abspath(db_path)
        parent = os.path.dirname(db_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        _DB_PATH = db_path
        _CONN = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        _CONN.row_factory = sqlite3.Row
        _CONN.execute("PRAGMA journal_mode=WAL")
        _CONN.execute("PRAGMA synchronous=NORMAL")
        _CONN.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_rooms (
                room_id       TEXT PRIMARY KEY,
                name          TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL DEFAULT '',
                created       REAL NOT NULL DEFAULT 0,
                last_activity REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id        TEXT PRIMARY KEY,
                room_id   TEXT NOT NULL,
                nick      TEXT NOT NULL DEFAULT '',
                content   TEXT NOT NULL DEFAULT '',
                timestamp REAL NOT NULL DEFAULT 0,
                seq       INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_chat_messages_room
                ON chat_messages(room_id, seq);

            CREATE TABLE IF NOT EXISTS temp_files (
                fid         TEXT PRIMARY KEY,
                name        TEXT,
                size        TEXT,
                path        TEXT,
                upload_time REAL,
                owner       TEXT
            );

            CREATE TABLE IF NOT EXISTS admin (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE,
                password_hash TEXT,
                totp_secret   TEXT,
                enabled       INTEGER DEFAULT 0
            );
            """
        )
        _CONN.commit()
    return db_path


def get_db_path():
    return _DB_PATH


# ===================== 聊天室 =====================
def save_chat(rooms):
    """持久化内存中的 chat_rooms 结构。

    rooms: {room_id: {name,password_hash,created,last_activity,messages:[...],users:set}}
    每次全量覆盖房间行，并重建该房间的消息行（保证与内存一致、且顺序稳定）。
    """
    with _LOCK:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("BEGIN")
        try:
            for rid, room in rooms.items():
                cur.execute(
                    """INSERT INTO chat_rooms(room_id,name,password_hash,created,last_activity)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(room_id) DO UPDATE SET
                         name=excluded.name,
                         password_hash=excluded.password_hash,
                         created=excluded.created,
                         last_activity=excluded.last_activity""",
                    (
                        rid,
                        room.get("name") or "",
                        room.get("password_hash") or "",
                        float(room.get("created", 0) or 0),
                        float(room.get("last_activity", 0) or 0),
                    ),
                )
                # 重建消息行
                cur.execute("DELETE FROM chat_messages WHERE room_id=?", (rid,))
                for seq, m in enumerate(room.get("messages", []) or []):
                    cur.execute(
                        """INSERT OR REPLACE INTO chat_messages(id,room_id,nick,content,timestamp,seq)
                           VALUES(?,?,?,?,?,?)""",
                        (
                            m.get("id") or "",
                            rid,
                            m.get("nick") or "",
                            m.get("content") or "",
                            float(m.get("timestamp", 0) or 0),
                            seq,
                        ),
                    )
            # 清理已被删除的房间
            placeholders = ",".join("?" for _ in rooms) or "NULL"
            cur.execute(f"DELETE FROM chat_rooms WHERE room_id NOT IN ({placeholders})",
                        tuple(rooms.keys()))
            cur.execute(f"DELETE FROM chat_messages WHERE room_id NOT IN ({placeholders})",
                        tuple(rooms.keys()))
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def load_chat():
    """从数据库读取，返回与内存一致的 dict 结构（messages 为 list，users 为空 set）。"""
    from collections import deque
    out = {}
    with _LOCK:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM chat_rooms")
        rooms = cur.fetchall()
        for r in rooms:
            rid = r["room_id"]
            cur.execute(
                "SELECT * FROM chat_messages WHERE room_id=? ORDER BY seq ASC", (rid,)
            )
            msgs = [
                {
                    "id": m["id"],
                    "nick": m["nick"],
                    "content": m["content"],
                    "timestamp": m["timestamp"],
                }
                for m in cur.fetchall()
            ]
            out[rid] = {
                "name": r["name"],
                "password_hash": r["password_hash"],
                "created": r["created"],
                "last_activity": r["last_activity"],
                "messages": list(msgs),
                "users": set(),
            }
    return out


# ===================== 临时文件 =====================
def save_temp(temp_files):
    """持久化内存中的 temp_files 结构：{fid: {name,size,path,upload_time,owner}}"""
    with _LOCK:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("BEGIN")
        try:
            for fid, info in temp_files.items():
                cur.execute(
                    """INSERT INTO temp_files(fid,name,size,path,upload_time,owner)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(fid) DO UPDATE SET
                         name=excluded.name, size=excluded.size, path=excluded.path,
                         upload_time=excluded.upload_time, owner=excluded.owner""",
                    (
                        fid,
                        info.get("name") or "",
                        str(info.get("size", "") or ""),
                        info.get("path") or "",
                        float(info.get("upload_time", 0) or 0),
                        info.get("owner") or "",
                    ),
                )
            placeholders = ",".join("?" for _ in temp_files) or "NULL"
            cur.execute(f"DELETE FROM temp_files WHERE fid NOT IN ({placeholders})",
                        tuple(temp_files.keys()))
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def load_temp():
    out = {}
    with _LOCK:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM temp_files")
        for r in cur.fetchall():
            out[r["fid"]] = {
                "name": r["name"],
                "size": r["size"],
                "path": r["path"],
                "upload_time": r["upload_time"],
                "owner": r["owner"],
            }
    return out


# ===================== 管理账号 =====================
def get_admin(username=None):
    with _LOCK:
        conn = _connect()
        cur = conn.cursor()
        if username:
            cur.execute("SELECT * FROM admin WHERE username=?", (username,))
        else:
            cur.execute("SELECT * FROM admin ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else None


def upsert_admin(username, password_hash, totp_secret, enabled=1):
    with _LOCK:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT id FROM admin WHERE username=?", (username,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE admin SET password_hash=?, totp_secret=?, enabled=? WHERE id=?",
                (password_hash, totp_secret, int(bool(enabled)), row["id"]),
            )
        else:
            cur.execute(
                "INSERT INTO admin(username,password_hash,totp_secret,enabled) VALUES(?,?,?,?)",
                (username, password_hash, totp_secret, int(bool(enabled))),
            )
        conn.commit()
        return True


# ===================== 从 JSON 迁移（一次性） =====================
def migrate_from_json(chat_json_path, temp_json_path, db_path=None):
    """若数据库为空，则把旧的 JSON 数据导入。返回 (chat_count, temp_count, migrated)。"""
    if db_path:
        init(db_path)
    with _LOCK:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM chat_rooms")
        existing = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM temp_files")
        existing += cur.fetchone()["c"]
        if existing > 0:
            return (0, 0, False)

    chat_count = temp_count = 0
    rooms = {}
    if chat_json_path and os.path.exists(chat_json_path):
        try:
            with open(chat_json_path, "r", encoding="utf-8") as f:
                rooms = json.load(f)
            for rid, room in rooms.items():
                room.setdefault("name", "")
                room.setdefault("password_hash", "")
                room.setdefault("created", 0)
                room.setdefault("last_activity", 0)
                room.setdefault("messages", [])
            chat_count = len(rooms)
        except Exception:
            rooms = {}
    if rooms:
        save_chat(rooms)

    temps = {}
    if temp_json_path and os.path.exists(temp_json_path):
        try:
            with open(temp_json_path, "r", encoding="utf-8") as f:
                temps = json.load(f)
            temp_count = len(temps)
        except Exception:
            temps = {}
    if temps:
        save_temp(temps)

    return (chat_count, temp_count, bool(chat_count or temp_count))
