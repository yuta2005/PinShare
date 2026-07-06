#!/usr/bin/python3
"""
PinSync - サーバー
複数クライアントの接続を管理し、ピン情報をブロードキャストする
担当: Aさん（サーバー・ロジック担当）
"""

import json
import socket
import threading

# ── 設定 ──────────────────────────────────────────
HOST = "localhost"
PORT = 9999
MAX_CLIENTS = 10

print("start server")


class PinSyncServer:
    def __init__(self):
        # 接続中のクライアント一覧 {socket: username}
        self.clients: dict[socket.socket, str] = {}
        self.lock = threading.Lock()

        # ピンデータを保持（新規参加者に送るため）
        # {pin_id: {type, user, lat, lng, category, comment}}
        self.pins: dict[str, dict] = {}
        self.pin_counter = 0

        # サーバーソケット（サンプルコードと同じ書き方）
        self.serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.serversocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.serversocket.bind((HOST, PORT))
        self.serversocket.listen(MAX_CLIENTS)

        print(f"waiting connection on {HOST}:{PORT} ...")

    # ── 起動 ──────────────────────────────────────

    def run(self):
        """接続を待ち続けるメインループ（サンプルの while True と同じ）"""
        while True:
            # サンプルコードと同じ: accept でクライアントを待つ
            clientsocket, addr = self.serversocket.accept()
            print(f"Got a connection from {addr}")

            # サンプルと違う点: 切断せずスレッドで並行処理
            t = threading.Thread(
                target=self._handle_client, args=(clientsocket,), daemon=True
            )
            t.start()

    # ── クライアント処理 ──────────────────────────

    def _handle_client(self, sock: socket.socket):
        """1クライアントの送受信を担当するスレッド"""
        buffer = ""
        try:
            while True:
                # サンプルコードと同じ: recv でデータを受信
                data = sock.recv(4096).decode("utf-8")
                if not data:
                    break

                buffer += data
                # 改行区切りで1メッセージずつ処理
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        self._handle_message(sock, json.loads(line))

        except Exception as e:
            print(f"[ERROR] クライアント処理エラー: {e}")
        finally:
            self._remove_client(sock)

    def _handle_message(self, sock: socket.socket, msg: dict):
        """受信したJSONを種類ごとに処理"""
        msg_type = msg.get("type")
        print(f"[RECV] {msg}")

        if msg_type == "JOIN":
            self._on_join(sock, msg)

        elif msg_type == "LEAVE":
            self._on_leave(sock, msg)

        elif msg_type == "PIN_ADD":
            self._on_pin_add(sock, msg)

        elif msg_type == "PIN_REMOVE":
            self._on_pin_remove(sock, msg)

        elif msg_type == "CHAT":
            self._broadcast(msg, exclude=None)

        else:
            print(f"[WARN] 未知のメッセージタイプ: {msg_type}")

    # ── イベント処理 ──────────────────────────────

    def _on_join(self, sock: socket.socket, msg: dict):
        """クライアント参加時の処理"""
        username = msg.get("user", "名無し")

        with self.lock:
            self.clients[sock] = username

        print(f"[JOIN] {username} が参加 (接続数: {len(self.clients)})")

        # 既存のピンを新規参加者に送信
        with self.lock:
            for pin in self.pins.values():
                self._send_to(sock, pin)

        # 全員に参加通知をブロードキャスト
        self._broadcast({"type": "JOIN", "user": username})

    def _on_leave(self, sock: socket.socket, msg: dict):
        """クライアント退出時の処理"""
        username = msg.get("user", "名無し")
        self._broadcast({"type": "LEAVE", "user": username})

    def _on_pin_add(self, sock: socket.socket, msg: dict):
        """ピン追加時の処理"""
        # pin_id を採番してメッセージに付与
        with self.lock:
            self.pin_counter += 1
            pin_id = f"pin_{self.pin_counter}"

        msg["pin_id"] = pin_id

        # ピンデータを保存
        with self.lock:
            self.pins[pin_id] = msg

        print(
            f"[PIN] {msg.get('user')} がピン追加: {msg.get('comment', '')} ({pin_id})"
        )

        # 全クライアントにブロードキャスト
        self._broadcast(msg)

    def _on_pin_remove(self, sock: socket.socket, msg: dict):
        """ピン削除時の処理"""
        pin_id = msg.get("pin_id")
        with self.lock:
            self.pins.pop(pin_id, None)

        print(f"[PIN] ピン削除: {pin_id}")
        self._broadcast(msg)

    def _remove_client(self, sock: socket.socket):
        """クライアントの切断処理"""
        with self.lock:
            username = self.clients.pop(sock, "不明")

        try:
            sock.close()
        except Exception:
            pass

        print(f"[LEAVE] {username} が切断 (接続数: {len(self.clients)})")
        self._broadcast({"type": "LEAVE", "user": username})

    # ── 送信 ──────────────────────────────────────

    def _send_to(self, sock: socket.socket, data: dict):
        """特定のクライアントにJSONを送信"""
        try:
            msg = json.dumps(data, ensure_ascii=False) + "\n"
            sock.send(msg.encode("utf-8"))
        except Exception as e:
            print(f"[ERROR] 送信失敗: {e}")

    def _broadcast(self, data: dict, exclude: socket.socket = None):
        """全クライアントにJSONをブロードキャスト"""
        with self.lock:
            targets = list(self.clients.keys())

        for sock in targets:
            if sock != exclude:
                self._send_to(sock, data)


# ── エントリーポイント ────────────────────────────

if __name__ == "__main__":
    server = PinSyncServer()
    server.run()
