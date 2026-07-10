"""
東京周辺の地図タイルを事前ダウンロードしてキャッシュDBに保存するスクリプト。
main.py とは別に、旅行前に1回だけ実行してください。

実行方法:
    python preload_tiles.py
"""

import os
import tkintermapview

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
cache_dir = os.path.join(BASE_DIR, "map_cache")
os.makedirs(cache_dir, exist_ok=True)
db_path = os.path.join(cache_dir, "offline_tiles.db")

# 東京周辺（山手線＋近郊エリアを広めにカバー）
top_left = (35.80, 139.60)      # 北西端（北区・板橋あたり）
bottom_right = (35.60, 139.85)  # 南東端（品川・江東あたり）

# ズームレベル：
#   10-13 = 広域（都市全体の把握）
#   14-16 = 街歩きレベル（駅・通り単位）
zoom_min = 10
zoom_max = 16

print(f"保存先: {db_path}")
print(f"範囲: {top_left} 〜 {bottom_right}")
print(f"ズーム: {zoom_min} 〜 {zoom_max}")
print("ダウンロード開始（範囲・ズームが広いと数分〜かかります）...")

loader = tkintermapview.OfflineLoader(path=db_path)
loader.save_offline_tiles(top_left, bottom_right, zoom_min, zoom_max)

print("完了！")
