#!/usr/bin/python3
"""
PinSync - サーバー
複数クライアントの接続を管理し、ピン情報をブロードキャストする
担当: Aさん（サーバー・ロジック担当）
"""

import socket
import threading

import protocol
from protocol import HOST, PORT, MAX_CLIENTS, MessageReader, send_json

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
        reader = MessageReader(sock)
        try:
            # MessageReader が UTF-8 境界と不正 JSON を吸収してくれるので
            # ここでは1メッセージずつ受け取って処理するだけでよい。
            for msg in reader.messages():
                self._handle_message(sock, msg)
        except Exception as e:
            print(f"[ERROR] クライアント処理エラー: {e}")
        finally:
            # 切断検知はここ一箇所に集約する（LEAVE の二重送信を防ぐ）
            self._remove_client(sock)

    def _handle_message(self, sock: socket.socket, msg: dict):
        """受信したJSONを種類ごとに処理"""
        msg_type = msg.get("type")
        print(f"[RECV] {msg}")

        if msg_type == protocol.JOIN:
            self._on_join(sock, msg)

        elif msg_type == protocol.LEAVE:
            self._on_leave(sock, msg)

        elif msg_type == protocol.PIN_ADD:
            self._on_pin_add(sock, msg)

        elif msg_type == protocol.PIN_REMOVE:
            self._on_pin_remove(sock, msg)

        elif msg_type == protocol.CHAT:
            self._broadcast(msg)

        else:
            print(f"[WARN] 未知のメッセージタイプ: {msg_type}")

    # ── イベント処理 ──────────────────────────────

    def _on_join(self, sock: socket.socket, msg: dict):
        """クライアント参加時の処理"""
        username = msg.get("user", "名無し")

        with self.lock:
            self.clients[sock] = username
            # ロックを長く握らないよう、送信対象のコピーだけ取る。
            # （ロック保持中にソケット送信すると、遅いクライアントで
            #   全スレッドが停止する恐れがあるため）
            existing_pins = list(self.pins.values())

        print(f"[JOIN] {username} が参加 (接続数: {len(self.clients)})")

        # 既存のピンを新規参加者に送信（ロック外で行う）
        for pin in existing_pins:
            self._send_to(sock, pin)

        # 他の参加者に参加通知（本人には送らない = 自分の参加通知を防ぐ）
        self._broadcast({"type": protocol.JOIN, "user": username}, exclude=sock)

    def _on_leave(self, sock: socket.socket, msg: dict):
        """
        クライアントからの明示的な LEAVE 受信。
        この直後にソケットが閉じられ _remove_client が呼ばれるため、
        ここでは通知しない（LEAVE の二重ブロードキャストを防ぐ）。
        """
        pass

    def _on_pin_add(self, sock: socket.socket, msg: dict):
        """ピン追加時の処理"""
        # pin_id を採番してメッセージに付与し、そのまま保存する
        with self.lock:
            self.pin_counter += 1
            pin_id = f"pin_{self.pin_counter}"
            msg["pin_id"] = pin_id
            self.pins[pin_id] = msg

        print(
            f"[PIN] {msg.get('user')} がピン追加: {msg.get('comment', '')} ({pin_id})"
        )

        # 全クライアントにブロードキャスト（送信者本人も自分のピンを表示できる）
        self._broadcast(msg)

    def _on_pin_remove(self, sock: socket.socket, msg: dict):
        """ピン削除時の処理"""
        pin_id = msg.get("pin_id")
        with self.lock:
            self.pins.pop(pin_id, None)

        print(f"[PIN] ピン削除: {pin_id}")
        self._broadcast(msg)

    def _remove_client(self, sock: socket.socket):
        """クライアントの切断処理（切断検知の唯一の入口）"""
        with self.lock:
            # 既に削除済みなら二重処理しない
            if sock not in self.clients:
                self._safe_close(sock)
                return
            username = self.clients.pop(sock)

        self._safe_close(sock)

        print(f"[LEAVE] {username} が切断 (接続数: {len(self.clients)})")
        self._broadcast({"type": protocol.LEAVE, "user": username})

    @staticmethod
    def _safe_close(sock: socket.socket):
        try:
            sock.close()
        except Exception:
            pass

    # ── 送信 ──────────────────────────────────────

    def _send_to(self, sock: socket.socket, data: dict):
        """特定のクライアントにJSONを送信"""
        try:
            send_json(sock, data)
        except Exception as e:
            # 送信失敗の後始末は各クライアントの受信スレッド（finally）に任せる。
            print(f"[ERROR] 送信失敗: {e}")

    def _broadcast(self, data: dict, exclude: socket.socket = None):
        """全クライアントにJSONをブロードキャスト"""
        with self.lock:
            # 送信はロック外で行う（ロック保持中の送信を避ける）
            targets = list(self.clients.keys())

        for sock in targets:
            if sock != exclude:
                self._send_to(sock, data)


# ── エントリーポイント ────────────────────────────

if __name__ == "__main__":
    server = PinSyncServer()
    server.run()
