#!/usr/bin/python3
"""
PinSync - 共通プロトコル
クライアントとサーバーで共有するメッセージ定義と送受信ヘルパー。

main.py と server.py に散らばっていた「メッセージタイプ文字列」や
「JSON を改行区切りで送受信する処理」をここに一本化する。
これにより両者のプロトコルのズレを防ぎ、UTF-8 境界や部分送信の
バグをまとめて解消する。
"""

import json
import socket

# ── 接続設定 ──────────────────────────────────────
HOST = "localhost"
PORT = 9999
MAX_CLIENTS = 10

# ── メッセージタイプ ──────────────────────────────
# 文字列を直書きすると打ち間違いで無言のバグになるため定数化する。
JOIN = "JOIN"
LEAVE = "LEAVE"
PIN_ADD = "PIN_ADD"
PIN_REMOVE = "PIN_REMOVE"
CHAT = "CHAT"

# ── カテゴリ定義 ──────────────────────────────────
CATEGORY_COLORS = {
    "food": "#E74C3C",  # 赤：食事
    "hotel": "#3498DB",  # 青：宿泊
    "sightseeing": "#2ECC71",  # 緑：観光
    "other": "#F39C12",  # 橙：その他
}

CATEGORY_LABELS = {
    "food": "🍜 食事",
    "hotel": "🏨 宿泊",
    "sightseeing": "🗼 観光",
    "other": "📌 その他",
}

DEFAULT_CATEGORY = "other"


def send_json(sock, data):
    """
    JSON を1メッセージ（改行終端）としてソケットに送信する。
    - ensure_ascii=False で日本語をそのまま送る。
    - sendall で send() の部分送信バグを防ぐ。
    """
    line = json.dumps(data, ensure_ascii=False) + "\n"
    sock.sendall(line.encode("utf-8"))


class MessageReader:
    """
    ソケットから改行区切りの JSON メッセージを1件ずつ取り出す。
    バイト単位でバッファリングするため、日本語が recv 境界で分割されても
    UnicodeDecodeError で落ちない。不正な JSON 行は接続を切らずスキップする。
    """

    def __init__(self, sock, bufsize=4096):
        self.sock = sock
        self.bufsize = bufsize
        self._buffer = b""

    def messages(self):
        while True:
            data = self.sock.recv(self.bufsize)
            if not data:  # 相手が切断
                return
            self._buffer += data
            while b"\n" in self._buffer:
                raw, self._buffer = self._buffer.split(b"\n", 1)
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    yield json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as err:
                    print("[WARN] 不正なメッセージを無視:", err)
                    continue
