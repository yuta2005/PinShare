#!/usr/bin/python3
"""
PinSync - クライアント
サーバーに接続し、地図上でピンを共有するGUIアプリ
担当: Bさん（クライアント・UI担当）
"""

import math
import queue
import socket
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

import tkintermapview

import protocol
from protocol import (
    HOST,
    PORT,
    CATEGORY_COLORS,
    CATEGORY_LABELS,
    DEFAULT_CATEGORY,
    MessageReader,
    send_json,
)


class PinSyncClient:
    def __init__(self):
        self.sock = None
        self.username = ""
        self.running = False
        self.markers = {}  # pin_id -> marker オブジェクト
        self.pin_data = {}  # pin_id -> ピン情報（タイムラインの行き先選択用）
        self.expenses = []  # 割り勘用：サーバーから受信した支出の一覧
        self.timeline = {}  # timeline_id -> 予定（データは常に本体側で保持）
        self.timeline_win = None  # タイムラインの別ウィンドウ（未表示なら None）
        self.manage_win = None  # 一覧・削除ウィンドウ（未表示なら None）

        # 受信スレッド → メインスレッドへの受け渡しキュー。
        # スレッドから root.after を直接呼ぶと、タイミングによって
        # RuntimeError で受信ループごと死ぬことがあるため、
        # スレッドは Queue に積むだけにして Tk には一切触らない。
        self.msg_queue = queue.Queue()

        self._build_ui()

        # メインスレッド側で100msごとにキューを処理する（tkinterの定石）
        self.root.after(100, self._poll_messages)

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

        # タイムラインは左パネルが手狭なため別ウィンドウ（Toplevel）で開く
        tk.Button(
            header,
            text="🕐 タイムライン",
            bg="#0A7CB0",
            fg="white",
            font=("Arial", 11, "bold"),
            relief="flat",
            cursor="hand2",
            command=self._open_timeline_window,
        ).pack(side="right", padx=4, pady=8)

        # ピン・支出の一覧表示と削除も別ウィンドウにまとめる
        tk.Button(
            header,
            text="📋 一覧・削除",
            bg="#0A7CB0",
            fg="white",
            font=("Arial", 11, "bold"),
            relief="flat",
            cursor="hand2",
            command=self._open_manage_window,
        ).pack(side="right", padx=4, pady=8)

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

        # 割り勘セクション
        self._section_label("割り勘")

        self.expense_title_entry = self._entry("支出タイトル（例：ランチ）")
        self.expense_price_entry = self._entry("金額（円）")

        tk.Button(
            self.panel,
            text="💰 支出を追加",
            bg="#02C39A",
            fg="white",
            font=("Arial", 11, "bold"),
            relief="flat",
            cursor="hand2",
            command=self._add_expense,
        ).pack(fill="x", padx=12, pady=(4, 6))

        # 人数入力（各自のローカル設定：値を変えるとすぐ再計算される）
        people_row = tk.Frame(self.panel, bg="#0F172A")
        people_row.pack(fill="x", padx=12, pady=2)

        tk.Label(
            people_row, text="人数:", bg="#0F172A", fg="white", font=("Arial", 11)
        ).pack(side="left")

        self.people_var = tk.StringVar(value="2")

        tk.Spinbox(
            people_row,
            from_=1,
            to=99,
            textvariable=self.people_var,
            width=5,
            font=("Arial", 11),
            relief="flat",
        ).pack(side="left", padx=8)

        # 合計・一人あたりの表示
        self.split_label = tk.Label(
            self.panel,
            text="合計 ¥0 ／ 一人 ¥0",
            bg="#0F172A",
            fg="#02C39A",
            font=("Arial", 12, "bold"),
        )
        self.split_label.pack(anchor="w", padx=12, pady=(4, 0))

        # 値の変更を検知して自動再計算。
        # 注意：trace は Spinbox 生成時にも発火しうるため、
        # 参照先の split_label を作った「後」に登録すること。
        self.people_var.trace_add("write", lambda *args: self._update_split())

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
            height=8,
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

        # サーバーIP欄が空／プレースホルダのままなら既定値にフォールバック
        if not host or host == "サーバーIP":
            host = HOST

        self.username = name

        try:
            # サンプルコードと同じ接続方法
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((host, PORT))
            self.running = True

            # 接続直後にユーザー名を送信
            self._send({"type": protocol.JOIN, "user": self.username})

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
            self._send({"type": protocol.LEAVE, "user": self.username})
            self.sock.close()
            self.sock = None
        self.status_label.config(text="未接続", fg="#94A3B8")
        self.connect_btn.config(text="接続する", command=self._connect)
        self._log("🔌 切断しました")

    # ── 送受信 ────────────────────────────────────

    def _send(self, data: dict):
        """JSONをサーバーに送信（sendall で部分送信を防ぐ）"""
        if not self.sock:
            return
        try:
            send_json(self.sock, data)
        except Exception as e:
            self._log(f"⚠️ 送信エラー: {e}")

    def _receive_loop(self):
        """
        サーバーからのメッセージを受信し続けるスレッド。

        Tkinter はスレッドセーフでないため、このスレッドは Tk に一切触らず、
        受信したメッセージを Queue に積むだけにする。
        画面反映は _poll_messages（メインスレッド）が行う。
        """
        reader = MessageReader(self.sock)
        try:
            for msg in reader.messages():
                if not self.running:
                    break
                self.msg_queue.put(msg)
        except Exception:
            pass
        finally:
            if self.running:
                # 切断もキュー経由でメインスレッドに通知する
                self.msg_queue.put({"type": "_DISCONNECTED"})

    def _poll_messages(self):
        """キューに溜まったメッセージをメインスレッドで処理する（100ms周期）"""
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                if msg.get("type") == "_DISCONNECTED":
                    self._log("⚠️ サーバーとの接続が切れました")
                else:
                    self._handle_message(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_messages)

    def _handle_message(self, msg: dict):
        """受信したJSONを種類ごとに処理（メインスレッドで実行される）"""
        msg_type = msg.get("type")

        if msg_type == protocol.PIN_ADD:
            self._add_marker(msg)

        elif msg_type == protocol.PIN_REMOVE:
            self._remove_marker(msg)

        elif msg_type == protocol.JOIN:
            self._log(f"👋 {msg.get('user')} が参加しました")

        elif msg_type == protocol.LEAVE:
            self._log(f"👋 {msg.get('user')} が退出しました")

        elif msg_type == protocol.CHAT:
            self._log(f"💬 {msg.get('user')}: {msg.get('text')}")

        elif msg_type == protocol.EXPENSE_ADD:
            self._on_expense_received(msg)

        elif msg_type == protocol.EXPENSE_REMOVE:
            self._on_expense_removed(msg)

        elif msg_type == protocol.TIMELINE_ADD:
            self._on_timeline_received(msg)

        elif msg_type == protocol.TIMELINE_REMOVE:
            self._on_timeline_removed(msg)

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
                "type": protocol.PIN_ADD,
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
        category = msg.get("category", DEFAULT_CATEGORY)
        color = CATEGORY_COLORS.get(category, CATEGORY_COLORS[DEFAULT_CATEGORY])
        label = f"{CATEGORY_LABELS.get(category, '📌')} {msg.get('user', '')}\n{msg.get('comment', '')}"

        marker = self.map.set_marker(
            msg["lat"],
            msg["lng"],
            text=label,
            marker_color_circle=color,
            marker_color_outside=color,
        )
        self.markers[pin_id] = marker
        self.pin_data[pin_id] = msg  # タイムラインの行き先選択用に情報も保持
        self._refresh_pin_choices()
        self._refresh_manage_lists()
        self._log(f"📍 {msg.get('user')} がピンを追加: {msg.get('comment', '')}")

    def _remove_marker(self, msg: dict):
        """地図からマーカーを削除"""
        pin_id = msg.get("pin_id")
        if pin_id in self.markers:
            self.markers[pin_id].delete()
            del self.markers[pin_id]
        removed = self.pin_data.pop(pin_id, None)
        self._refresh_pin_choices()
        self._refresh_manage_lists()
        if removed:
            self._log(f"🗑 ピンを削除: {removed.get('comment', '')}")

    # ── 割り勘 ────────────────────────────────────

    def _add_expense(self):
        """「支出を追加」ボタン押下時：入力を検証してサーバーに送信"""
        if not self.sock:
            messagebox.showinfo("未接続", "先にサーバーに接続してください")
            return

        title = self.expense_title_entry.get().strip()
        price_text = self.expense_price_entry.get().strip()

        if not title or title == "支出タイトル（例：ランチ）":
            messagebox.showwarning("入力エラー", "支出のタイトルを入力してください")
            return

        try:
            price = int(price_text)
            if price <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                "入力エラー", "金額は1以上の整数で入力してください"
            )
            return

        # ピンと同じく、サーバー経由で全員（自分含む）に届いてから画面に反映する
        self._send(
            {
                "type": protocol.EXPENSE_ADD,
                "user": self.username,
                "title": title,
                "price": price,
            }
        )

        # 入力欄をクリアして次の入力に備える
        self.expense_title_entry.delete(0, "end")
        self.expense_price_entry.delete(0, "end")

    def _on_expense_received(self, msg: dict):
        """サーバーから支出を受信：一覧に追加して合計を再計算"""
        self.expenses.append(msg)
        self._log(f"💰 {msg.get('user')}: {msg.get('title')} ¥{msg.get('price', 0):,}")
        self._update_split()
        self._refresh_manage_lists()

    def _on_expense_removed(self, msg: dict):
        """サーバーから支出削除を受信：一覧から除いて合計を再計算"""
        expense_id = msg.get("expense_id")
        self.expenses = [
            e for e in self.expenses if e.get("expense_id") != expense_id
        ]
        self._log("🗑 支出を削除しました")
        self._update_split()
        self._refresh_manage_lists()

    def _update_split(self):
        """合計金額と一人あたりの金額を計算して表示を更新"""
        if not hasattr(self, "split_label"):  # UI構築中は何もしない
            return
        total = sum(e.get("price", 0) for e in self.expenses)

        try:
            people = int(self.people_var.get())
        except (ValueError, tk.TclError):
            people = 1  # 入力途中（空欄など）は1人として扱う
        if people < 1:
            people = 1

        # 割り切れない場合は切り上げ（実際の割り勘で不足が出ないように）
        per_person = math.ceil(total / people)

        self.split_label.config(text=f"合計 ¥{total:,} ／ 一人 ¥{per_person:,}")

    # ── タイムライン ──────────────────────────────

    def _open_timeline_window(self):
        """
        タイムラインを別ウィンドウ（Toplevel）で開く。
        データ本体は self.timeline に常に保持しているため、
        ウィンドウを閉じている間に届いた予定も、開き直せば表示される。
        """
        # 二重に開かない：既に開いていれば前面に出すだけ
        if self.timeline_win is not None and self.timeline_win.winfo_exists():
            self.timeline_win.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("PinSync - タイムライン")
        win.geometry("440x540")
        win.configure(bg="#0F172A")
        self.timeline_win = win

        tk.Label(
            win,
            text="🕐 タイムライン",
            bg="#0F172A",
            fg="white",
            font=("Arial", 14, "bold"),
        ).pack(anchor="w", padx=16, pady=(12, 0))

        tk.Label(
            win,
            text="何時にどのピンへ行くかをみんなで共有できます",
            bg="#0F172A",
            fg="#64748B",
            font=("Arial", 10),
        ).pack(anchor="w", padx=16, pady=(0, 8))

        # ── 入力フォーム ──
        form = tk.Frame(win, bg="#0F172A")
        form.pack(fill="x", padx=16)

        tk.Label(
            form, text="時刻 (例 09:30)", bg="#0F172A", fg="#94A3B8", font=("Arial", 9)
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            form, text="行き先（ピンから選択）", bg="#0F172A", fg="#94A3B8", font=("Arial", 9)
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))

        self.time_entry = tk.Entry(
            form,
            width=8,
            bg="#1E293B",
            fg="white",
            insertbackground="white",
            relief="flat",
            font=("Arial", 11),
        )
        self.time_entry.grid(row=1, column=0, sticky="w", ipady=5)

        self.pin_combo = ttk.Combobox(form, state="readonly", width=28)
        self.pin_combo.grid(row=1, column=1, sticky="ew", padx=(12, 0))
        form.columnconfigure(1, weight=1)
        self._refresh_pin_choices()

        tk.Label(
            form, text="メモ（任意）", bg="#0F172A", fg="#94A3B8", font=("Arial", 9)
        ).grid(row=2, column=0, sticky="w", pady=(8, 0), columnspan=2)

        self.timeline_memo_entry = tk.Entry(
            form,
            bg="#1E293B",
            fg="white",
            insertbackground="white",
            relief="flat",
            font=("Arial", 11),
        )
        self.timeline_memo_entry.grid(
            row=3, column=0, columnspan=2, sticky="ew", ipady=5
        )

        tk.Button(
            win,
            text="🕐 予定を追加",
            bg="#02C39A",
            fg="white",
            font=("Arial", 11, "bold"),
            relief="flat",
            cursor="hand2",
            command=self._add_timeline_entry,
        ).pack(fill="x", padx=16, pady=8)

        # ── 予定一覧（時刻順） ──
        list_frame = tk.Frame(win, bg="#0F172A")
        list_frame.pack(fill="both", expand=True, padx=16)

        self.timeline_listbox = tk.Listbox(
            list_frame,
            bg="#1E293B",
            fg="#CBD5E1",
            font=("Arial", 11),
            relief="flat",
            selectbackground="#065A82",
            activestyle="none",
        )
        self.timeline_listbox.pack(side="left", fill="both", expand=True)
        # ダブルクリックでその予定のピンへ地図をジャンプ
        self.timeline_listbox.bind("<Double-Button-1>", self._jump_to_timeline_pin)

        scrollbar = tk.Scrollbar(list_frame, command=self.timeline_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.timeline_listbox.config(yscrollcommand=scrollbar.set)

        tk.Label(
            win,
            text="ダブルクリック: 地図でその場所を表示",
            bg="#0F172A",
            fg="#64748B",
            font=("Arial", 9),
        ).pack(anchor="w", padx=16, pady=(4, 0))

        tk.Button(
            win,
            text="選択した予定を削除",
            bg="#E74C3C",
            fg="white",
            font=("Arial", 10, "bold"),
            relief="flat",
            cursor="hand2",
            command=self._remove_timeline_entry,
        ).pack(fill="x", padx=16, pady=(4, 12))

        # 開いた時点で保持しているデータを描画
        self._refresh_timeline_list()

    def _refresh_pin_choices(self):
        """行き先プルダウンの選択肢を、現在のピン一覧から作り直す"""
        # ウィンドウが開いていない時は何もしない
        if self.timeline_win is None or not self.timeline_win.winfo_exists():
            return
        self._pin_choice_map = {}
        choices = []
        for pin_id, pin in self.pin_data.items():
            category = pin.get("category", DEFAULT_CATEGORY)
            label = f"{CATEGORY_LABELS.get(category, '📌')} {pin.get('comment', '')} ({pin.get('user', '')})"
            self._pin_choice_map[label] = pin_id
            choices.append(label)
        self.pin_combo["values"] = choices

    def _add_timeline_entry(self):
        """「予定を追加」ボタン押下時：入力を検証してサーバーに送信"""
        if not self.sock:
            messagebox.showinfo("未接続", "先にサーバーに接続してください", parent=self.timeline_win)
            return

        # 時刻の検証："9:30" のような入力も "09:30" に正規化する
        raw_time = self.time_entry.get().strip()
        try:
            time_str = datetime.strptime(raw_time, "%H:%M").strftime("%H:%M")
        except ValueError:
            messagebox.showwarning(
                "入力エラー", "時刻は 09:30 のような形式で入力してください",
                parent=self.timeline_win,
            )
            return

        # 行き先ピンの検証
        label = self.pin_combo.get()
        pin_id = getattr(self, "_pin_choice_map", {}).get(label)
        if not pin_id:
            messagebox.showwarning(
                "入力エラー",
                "行き先のピンを選択してください\n（ピンがない場合は先に地図をクリックして追加）",
                parent=self.timeline_win,
            )
            return

        memo = self.timeline_memo_entry.get().strip()

        # place はラベルのスナップショットも送る（後でピンが消えても表示できるように）
        self._send(
            {
                "type": protocol.TIMELINE_ADD,
                "user": self.username,
                "time": time_str,
                "pin_id": pin_id,
                "place": label,
                "memo": memo,
            }
        )

        self.time_entry.delete(0, "end")
        self.timeline_memo_entry.delete(0, "end")

    def _remove_timeline_entry(self):
        """一覧で選択中の予定を削除（サーバー経由で全員に反映）"""
        selection = self.timeline_listbox.curselection()
        if not selection:
            return
        timeline_id = self._timeline_ids[selection[0]]
        self._send(
            {
                "type": protocol.TIMELINE_REMOVE,
                "user": self.username,
                "timeline_id": timeline_id,
            }
        )

    def _jump_to_timeline_pin(self, event):
        """予定をダブルクリックしたら、そのピンの位置に地図を移動"""
        selection = self.timeline_listbox.curselection()
        if not selection:
            return
        entry = self.timeline.get(self._timeline_ids[selection[0]])
        if not entry:
            return
        pin = self.pin_data.get(entry.get("pin_id"))
        if pin:
            self.map.set_position(pin["lat"], pin["lng"])
            self.map.set_zoom(15)

    def _on_timeline_received(self, msg: dict):
        """サーバーから予定を受信：保持して一覧を更新"""
        timeline_id = msg.get("timeline_id")
        if not timeline_id:
            return
        self.timeline[timeline_id] = msg
        self._log(f"🕐 {msg.get('user')} が予定を追加: {msg.get('time')} {msg.get('place', '')}")
        self._refresh_timeline_list()

    def _on_timeline_removed(self, msg: dict):
        """サーバーから予定削除を受信"""
        self.timeline.pop(msg.get("timeline_id"), None)
        self._refresh_timeline_list()

    def _refresh_timeline_list(self):
        """タイムライン一覧を時刻順に描画し直す（ウィンドウが開いている時だけ）"""
        if self.timeline_win is None or not self.timeline_win.winfo_exists():
            return

        # "HH:MM" にゼロ埋めしてあるので、文字列ソート＝時刻順になる
        entries = sorted(self.timeline.values(), key=lambda e: e.get("time", ""))

        # listbox の行番号 → timeline_id の対応表（削除・ジャンプで使う）
        self._timeline_ids = [e["timeline_id"] for e in entries]

        self.timeline_listbox.delete(0, "end")
        for e in entries:
            memo = f" - {e['memo']}" if e.get("memo") else ""
            self.timeline_listbox.insert(
                "end", f"{e.get('time')}  {e.get('place', '')}{memo}"
            )

    # ── 一覧・削除ウィンドウ ──────────────────────

    def _open_manage_window(self):
        """ピンと支出の一覧・削除を1つの別ウィンドウにまとめて表示する"""
        if self.manage_win is not None and self.manage_win.winfo_exists():
            self.manage_win.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("PinSync - 一覧・削除")
        win.geometry("440x560")
        win.configure(bg="#0F172A")
        self.manage_win = win

        # ── ピン一覧 ──
        tk.Label(
            win, text="📍 ピン一覧", bg="#0F172A", fg="white",
            font=("Arial", 13, "bold"),
        ).pack(anchor="w", padx=16, pady=(12, 4))

        self.pin_listbox = tk.Listbox(
            win, bg="#1E293B", fg="#CBD5E1", font=("Arial", 11),
            relief="flat", selectbackground="#065A82", activestyle="none",
            height=8,
        )
        self.pin_listbox.pack(fill="both", expand=True, padx=16)

        tk.Button(
            win, text="選択したピンを削除", bg="#E74C3C", fg="white",
            font=("Arial", 10, "bold"), relief="flat", cursor="hand2",
            command=self._delete_selected_pin,
        ).pack(fill="x", padx=16, pady=(4, 12))

        # ── 支出一覧 ──
        tk.Label(
            win, text="💰 支出一覧（割り勘）", bg="#0F172A", fg="white",
            font=("Arial", 13, "bold"),
        ).pack(anchor="w", padx=16, pady=(0, 4))

        self.expense_listbox = tk.Listbox(
            win, bg="#1E293B", fg="#CBD5E1", font=("Arial", 11),
            relief="flat", selectbackground="#065A82", activestyle="none",
            height=8,
        )
        self.expense_listbox.pack(fill="both", expand=True, padx=16)

        tk.Button(
            win, text="選択した支出を削除", bg="#E74C3C", fg="white",
            font=("Arial", 10, "bold"), relief="flat", cursor="hand2",
            command=self._delete_selected_expense,
        ).pack(fill="x", padx=16, pady=(4, 12))

        # 開いた時点のデータを描画
        self._refresh_manage_lists()

    def _refresh_manage_lists(self):
        """ピン一覧・支出一覧を描画し直す（ウィンドウが開いている時だけ）"""
        if self.manage_win is None or not self.manage_win.winfo_exists():
            return

        # ピン一覧（行番号 → pin_id の対応表を同時に作る）
        self._pinlist_ids = list(self.pin_data.keys())
        self.pin_listbox.delete(0, "end")
        for pin_id in self._pinlist_ids:
            pin = self.pin_data[pin_id]
            category = pin.get("category", DEFAULT_CATEGORY)
            self.pin_listbox.insert(
                "end",
                f"{CATEGORY_LABELS.get(category, '📌')} "
                f"{pin.get('comment', '')} ({pin.get('user', '')})",
            )

        # 支出一覧（行番号 → expense_id の対応表を同時に作る）
        self._expenselist_ids = [e.get("expense_id") for e in self.expenses]
        self.expense_listbox.delete(0, "end")
        for e in self.expenses:
            self.expense_listbox.insert(
                "end", f"{e.get('title', '')} ¥{e.get('price', 0):,} ({e.get('user', '')})"
            )

    def _delete_selected_pin(self):
        """一覧で選択中のピンを削除（サーバー経由で全員に反映）"""
        selection = self.pin_listbox.curselection()
        if not selection:
            return
        pin_id = self._pinlist_ids[selection[0]]
        pin = self.pin_data.get(pin_id, {})
        if not messagebox.askyesno(
            "確認",
            f"ピン「{pin.get('comment', '')}」を削除しますか？\n（全員の地図から消えます）",
            parent=self.manage_win,
        ):
            return
        self._send(
            {"type": protocol.PIN_REMOVE, "user": self.username, "pin_id": pin_id}
        )

    def _delete_selected_expense(self):
        """一覧で選択中の支出を削除（サーバー経由で全員に反映）"""
        selection = self.expense_listbox.curselection()
        if not selection:
            return
        expense_id = self._expenselist_ids[selection[0]]
        self._send(
            {
                "type": protocol.EXPENSE_REMOVE,
                "user": self.username,
                "expense_id": expense_id,
            }
        )

    # ── ログ ──────────────────────────────────────

    def _log(self, text: str):
        """アクティビティログに追記（必ずメインスレッドから呼ぶこと）"""
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
