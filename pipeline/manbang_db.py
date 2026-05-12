from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qs

import pymysql


_DEFAULT_DSN = "root:12345678@tcp(localhost:3306)/tts_dev?charset=utf8mb4&parseTime=true&loc=Local"
_DSN_ENV = "MANBANG_MYSQL_DSN"
_DSN_PATTERN = re.compile(r"^([^:]+):([^@]*)@tcp\(([^:)]+):(\d+)\)/([^?]+)(?:\?(.*))?$")


@dataclass(frozen=True)
class MySQLConfig:
    user: str
    password: str
    host: str
    port: int
    database: str
    charset: str


def _parse_dsn(dsn: str) -> MySQLConfig:
    match = _DSN_PATTERN.match(dsn)
    if not match:
        raise ValueError("MANBANG_MYSQL_DSN 格式错误，应类似 user:pass@tcp(host:port)/db?charset=utf8mb4")
    user, password, host, port, database, query = match.groups()
    params = parse_qs(query or "")
    charset = params.get("charset", ["utf8mb4"])[0]
    return MySQLConfig(
        user=user,
        password=password,
        host=host,
        port=int(port),
        database=database,
        charset=charset,
    )


def _connect():
    cfg = _parse_dsn(os.environ.get(_DSN_ENV, _DEFAULT_DSN))
    return pymysql.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        database=cfg.database,
        charset=cfg.charset,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=3,
        read_timeout=5,
        write_timeout=5,
    )


def find_existing_voice_id(shipper_id: str) -> str | None:
    """按货主 ID 查询已存在的音色 ID。"""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT voice_id FROM manbang WHERE m_id=%s AND voice_id IS NOT NULL AND voice_id<>'' LIMIT 1",
                (shipper_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return str(row["voice_id"])


def upsert_voice_id(shipper_id: str, voice_id: str):
    """Step 6 成功后记录货主与最终音色 ID，供 Step 1 去重。"""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO manbang (m_id, voice_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE voice_id=VALUES(voice_id)
                """,
                (shipper_id, voice_id),
            )


def delete_voice_record(voice_id: str):
    """Step 7 删除远端音色后，同步删除本地去重表记录。"""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM manbang WHERE voice_id=%s", (voice_id,))
