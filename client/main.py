#!/usr/bin/python3
"""
PinSync - クライアント
サーバーに接続し、地図上でピンを共有するGUIアプリ
担当: Bさん（クライアント・UI担当）
"""

import json
import socket
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog

import tkintermapview

# ── 設定 ──────────────────────────────────────────
HOST = "localhost"
PORT = 9999

# カテゴリごとのピンの色
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


class PinSyncClient:
    def __init__(self):
        self.sock = None
        self.username = ""
        self.running = False
        self.markers = {}  # pin_id -> marker オブジェクト

        self._build_ui()

    # ── UI構築 ────────────────────────────────────

    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("PinSync - グループ旅行プランナー")
        self.root.geometry("1100x700")
        self.root.configure(bg="#1E293B")

        # ── ヘッダー ──
        header = tk.Frame(self.root, bg="#065A82", height=50)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="🗺️ PinSync",
            bg="#065A82",
            fg="white",
            font=("Arial", 18, "bold"),
        ).pack(side="left", padx=16)

        self.status_label = tk.Label(
            header, text="未接続", bg="#065A82", fg="#94A3B8", font=("Arial", 11)
        )
        self.status_label.pack(side="right", padx=16)

        # ── メインエリア（左パネル + 地図） ──
        main = tk.Frame(self.root, bg="#1E293B")
        main.pack(fill="both", expand=True)

        # 左パネル
        self.panel = tk.Frame(main, bg="#0F172A", width=260)
        self.panel.pack(side="left", fill="y")
        self.panel.pack_propagate(False)

        self._build_panel()

        # 地図エリア
        map_frame = tk.Frame(main, bg="#1E293B")
        map_frame.pack(side="left", fill="both", expand=True)

        self.map = tkintermapview.TkinterMapView(map_frame, corner_radius=0)
        self.map.pack(fill="both", expand=True)
        self.map.set_position(35.6812, 139.7671)  # 初期位置：東京
        self.map.set_zoom(12)
        self.map.add_left_click_map_command(self._on_map_click)

    def _build_panel(self):
        """左パネルの中身を構築"""

        # 接続セクション
        self._section_label("接続")

        self.name_entry = self._entry("ニックネーム")
        self.host_entry = self._entry("サーバーIP", HOST)

        self.connect_btn = tk.Button(
            self.panel,
            text="接続する",
            bg="#065A82",
            fg="white",
            font=("Arial", 11, "bold"),
            relief="flat",
            cursor="hand2",
            command=self._connect,
        )
        self.connect_btn.pack(fill="x", padx=12, pady=(4, 12))

        # カテゴリ選択
        self._section_label("ピンのカテゴリ")

        self.category_var = tk.StringVar(value="food")
        for key, label in CATEGORY_LABELS.items():
            tk.Radiobutton(
                self.panel,
                text=label,
                variable=self.category_var,
                value=key,
                bg="#0F172A",
                fg="white",
                selectcolor="#065A82",
                activebackground="#0F172A",
                activeforeground="white",
                font=("Arial", 11),
            ).pack(anchor="w", padx=16, pady=2)

        # ログエリア
        self._section_label("アクティビティ")

        self.log_text = tk.Text(
            self.panel,
            bg="#1E293B",
            fg="#CBD5E1",
            font=("Arial", 10),
            relief="flat",
            state="disabled",
            wrap="word",
            height=12,
        )
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _section_label(self, text):
        tk.Label(
            self.panel,
            text=text.upper(),
            bg="#0F172A",
            fg="#64748B",
            font=("Arial", 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 4))

    def _entry(self, placeholder, default=""):
        entry = tk.Entry(
            self.panel,
            bg="#1E293B",
            fg="white",
            insertbackground="white",
            relief="flat",
            font=("Arial", 11),
        )
        entry.insert(0, default if default else placeholder)
        entry.pack(fill="x", padx=12, pady=2, ipady=6)
        return entry

    # ── 接続処理 ──────────────────────────────────

    def _connect(self):
        name = self.name_entry.get().strip()
        host = self.host_entry.get().strip()

        if not name or name == "ニックネーム":
            messagebox.showwarning("入力エラー", "ニックネームを入力してください")
            return

        self.username = name

        try:
            # サンプルコードと同じ接続方法
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((host, PORT))
            self.running = True

            # 接続直後にユーザー名を送信
            self._send({"type": "JOIN", "user": self.username})

            # 受信スレッド開始
            t = threading.Thread(target=self._receive_loop, daemon=True)
            t.start()

            self.status_label.config(text=f"接続中: {self.username}", fg="#02C39A")
            self.connect_btn.config(text="切断する", command=self._disconnect)
            self._log(f"✅ サーバーに接続しました ({host}:{PORT})")

        except Exception as e:
            messagebox.showerror("接続エラー", str(e))

    def _disconnect(self):
        self.running = False
        if self.sock:
            self._send({"type": "LEAVE", "user": self.username})
            self.sock.close()
            self.sock = None
        self.status_label.config(text="未接続", fg="#94A3B8")
        self.connect_btn.config(text="接続する", command=self._connect)
        self._log("🔌 切断しました")

    # ── 送受信 ────────────────────────────────────

    def _send(self, data: dict):
        """JSONをサーバーに送信"""
        if not self.sock:
            return
        try:
            msg = json.dumps(data, ensure_ascii=False) + "\n"
            self.sock.send(msg.encode("utf-8"))
        except Exception as e:
            self._log(f"⚠️ 送信エラー: {e}")

    def _receive_loop(self):
        """サーバーからのメッセージを受信し続けるスレッド"""
        buffer = ""
        while self.running:
            try:
                data = self.sock.recv(4096).decode("utf-8")
                if not data:
                    break
                buffer += data
                # 改行区切りで複数メッセージを処理
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        self._handle_message(json.loads(line))
            except Exception:
                break
        self._log("⚠️ サーバーとの接続が切れました")

    def _handle_message(self, msg: dict):
        """受信したJSONを種類ごとに処理"""
        msg_type = msg.get("type")

        if msg_type == "PIN_ADD":
            self.root.after(0, self._add_marker, msg)

        elif msg_type == "PIN_REMOVE":
            self.root.after(0, self._remove_marker, msg)

        elif msg_type == "JOIN":
            self._log(f"👋 {msg.get('user')} が参加しました")

        elif msg_type == "LEAVE":
            self._log(f"👋 {msg.get('user')} が退出しました")

        elif msg_type == "CHAT":
            self._log(f"💬 {msg.get('user')}: {msg.get('text')}")

    # ── 地図操作 ──────────────────────────────────

    def _on_map_click(self, coords):
        """地図クリック時にピンを追加"""
        if not self.sock:
            messagebox.showinfo("未接続", "先にサーバーに接続してください")
            return

        lat, lng = coords
        category = self.category_var.get()

        # コメントを入力
        comment = simpledialog.askstring(
            "ピンを追加",
            f"ピンのメモを入力してください\n({CATEGORY_LABELS[category]})",
            parent=self.root,
        )
        if comment is None:  # キャンセル
            return

        self._send(
            {
                "type": "PIN_ADD",
                "user": self.username,
                "lat": lat,
                "lng": lng,
                "category": category,
                "comment": comment,
            }
        )

    def _add_marker(self, msg: dict):
        """地図にマーカーを追加"""
        pin_id = msg.get("pin_id", f"{msg['lat']},{msg['lng']}")
        category = msg.get("category", "other")
        color = CATEGORY_COLORS.get(category, "#F39C12")
        label = f"{CATEGORY_LABELS.get(category, '📌')} {msg.get('user', '')}\n{msg.get('comment', '')}"

        marker = self.map.set_marker(
            msg["lat"],
            msg["lng"],
            text=label,
            marker_color_circle=color,
            marker_color_outside=color,
        )
        self.markers[pin_id] = marker
        self._log(f"📍 {msg.get('user')} がピンを追加: {msg.get('comment', '')}")

    def _remove_marker(self, msg: dict):
        """地図からマーカーを削除"""
        pin_id = msg.get("pin_id")
        if pin_id in self.markers:
            self.markers[pin_id].delete()
            del self.markers[pin_id]

    # ── ログ ──────────────────────────────────────

    def _log(self, text: str):
        """アクティビティログに追記"""
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # ── 起動 ──────────────────────────────────────

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        if self.sock:
            self._disconnect()
        self.root.destroy()


if __name__ == "__main__":
    app = PinSyncClient()
    app.run()
