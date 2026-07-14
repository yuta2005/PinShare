# PinShare

**グループ旅行リアルタイム共有マップアプリ**

友達グループで地図上にピンを立てながら、日程投票・行き先提案・割り勘計算・タイムライン作成をリアルタイムで共有できるデスクトップアプリです。

---

##  技術スタック

| 要素 | 技術 |
|------|------|
| 言語 | Python 3.10+ |
| 通信 | socket + threading（TCP） |
| 地図 | tkintermapview（OpenStreetMap） |
| GUI | tkinter |
| データ | JSON |
| 通知 | plyer |

---

## セットアップ

### 1. リポジトリをクローン
```bash
git clone <URL>
cd PinSync
```

### 2. VS Code で開く
```bash
code .
```
→ 右下に「推奨拡張機能をインストールしますか？」が出たら **インストール** を押す

### 3. 仮想環境を作成・有効化
```powershell
python -m venv venv
venv\Scripts\activate
```

### 4. ライブラリをインストール
```powershell
pip install -r requirements.txt
```

### 5. 動作確認
```powershell
python -c "import tkintermapview; print('OK')"
```
→ `OK` が表示されればセットアップ完了！

---

##  起動方法

### サーバー起動
```powershell
python server/server.py
```

### クライアント起動
```powershell
python client/main.py
```

---

## フォルダ構成

```
PinSync/
├── .vscode/
│   ├── extensions.json   # 推奨拡張機能
│   └── settings.json     # VS Code 設定
├── server/
│   ├─ server.py         # TCPサーバー
│ 　└── protocol.py       # JSONメッセージ定義（共通）
├── client/
│   ├── main.py           # クライアントGUI
│   └── protocol.py       # JSONメッセージ定義（共通）
│  
├── requirements.txt
└── README.md
```

---

