# motopuppu/constants.py

# --- SettingSheet機能 関連 ---
SETTING_KEY_MAP = {
    "sprocket": {
        "title": "スプロケット",
        "keys": {
            "front_teeth": "フロント (T)",
            "rear_teeth": "リア (T)"
        }
    },
    # ▼▼▼【ここから追記】▼▼▼
    "chain": {
        "title": "チェーン",
        "keys": {
            "chain_brand": "チェーン銘柄",
            "chain_size": "チェーンサイズ",
            "chain_links": "リンク数"
        }
    },
    # ▲▲▲【追記はここまで】▲▲▲
    "ignition": {
        "title": "点火",
        "keys": {
            "spark_plug": "プラグ"
        }
    },
    "suspension": {
        "title": "サスペンション",
        "keys": {
            # フロント
            "front_protrusion_mm": "F: 突き出し(mm)",
            "front_preload": "F: プリロード",
            "front_spring_rate_nm": "F: スプリングレート(Nm)",
            "front_fork_oil": "F: フォークオイル",
            "front_oil_level_mm": "F: 油面(mm)",
            "front_damping_compression": "F: 減衰(圧側)",
            "front_damping_rebound": "F: 減衰(伸側)",
            # リア
            "rear_spring_rate_nm": "R: スプリングレート(Nm)",
            "rear_preload": "R: プリロード",
            "rear_damping_compression": "R: 減衰(圧側)",
            "rear_damping_rebound": "R: 減衰(伸側)"
        }
    },
    "tire": {
        "title": "タイヤ",
        "keys": {
            "tire_brand": "タイヤ銘柄",
            "tire_compound": "コンパウンド",
            "tire_pressure_kpa": "空気圧(kPa)"
        }
    },
    "carburetor": {
        "title": "キャブレター",
        "keys": {
            "main_jet": "メインジェット",
            "slow_jet": "スロージェット",
            "needle": "ニードル",
            "clip_position": "クリップ位置",
            "idle_screw": "アイドルスクリュー"
        }
    },
    "ecu": {
        "title": "ECU",
        "keys": {
            "map_name": "セット名"
        }
    }
}


# --- Forms 関連 ---

# スタンド名の候補リスト (FuelForm用)
GAS_STATION_BRANDS = [
    'ENEOS', '出光興産/apollostation', 'コスモ石油', 'キグナス石油', 'JA-SS', 'SOLATO',
]

# 日本の二輪走行可能サーキットリスト (ActivityLogForm用)
JAPANESE_CIRCUITS = [
    # --- 北海道 / 東北 ---
    "十勝スピードウェイ",
    "スポーツランドSUGO",
    "エビスサーキット東コース",
    "エビスサーキット西コース",
    
    # --- 関東 ---
    "ツインリンクもてぎ ロードコース",
    "筑波サーキット TC2000",
    "筑波サーキット TC1000",
    "袖ヶ浦フォレストレースウェイ",
    "桶川スポーツランド ロングコース",
    "桶川スポーツランド ミドルコース",
    "桶川スポーツランド ショートコース",
    "ヒーローしのいサーキット",
    "日光サーキット",
    "井頭モーターパーク",
    "茂原ツインサーキット ショートコース(西)",
    "茂原ツインサーキット ロングコース(東)",
    
    # --- 中部 / 東海 ---
    "富士スピードウェイ 本コース",
    "富士スピードウェイ ショートコース",
    "富士スピードウェイ カートコース",
    "白糸スピードランド",
    "スパ西浦モーターパーク",
    "モーターランド三河",
    "YZサーキット東コース",
    "鈴鹿ツインサーキット",
    "モーターランド鈴鹿",
    
    # --- 近畿 ---
    "鈴鹿サーキット フルコース",
    "鈴鹿サーキット 南コース",
    "近畿スポーツランド",
    "レインボースポーツ カートコース",
    "セントラルサーキット",
    "岡山国際サーキット",
    
    # --- 中国 / 四国 ---
    "TSタカタサーキット",
    "瀬戸内海サーキット",
    
    # --- 九州 / 沖縄 ---
    "オートポリス",
    "HSR九州",
]

# 油種の選択肢 (FuelForm用)
FUEL_TYPE_CHOICES = [
    ('', '--- 選択してください ---'),
    ('レギュラー', 'レギュラー'),
    ('ハイオク', 'ハイオク'),
    ('軽油', '軽油'),
    ('混合', '混合')
]

# カテゴリの候補リスト (MaintenanceForm用)
MAINTENANCE_CATEGORIES = [
    'エンジンオイル交換', 'タイヤ交換', 'ブレーキパッド交換', 'チェーンメンテナンス',
    '定期点検', '洗車', 'その他',
]

# ノート/タスクのカテゴリ (NoteForm用)
NOTE_CATEGORIES = [
    ('note', 'ノート'),
    ('task', 'タスク (TODOリスト)')
]

# TODOリストの最大アイテム数 (NoteForm用)
MAX_TODO_ITEMS = 50


# --- Leaderboard 関連 ---
TARGET_CIRCUITS = [
    "桶川スポーツランド ロングコース",
    "桶川スポーツランド ミドルコース",
    "桶川スポーツランド ショートコース",
    "井頭モーターパーク",
    "茂原ツインサーキット ショートコース(西)",
    "茂原ツインサーキット ロングコース(東)",
    "白糸スピードランド",
    "スパ西浦モーターパーク",
    "レインボースポーツ カートコース",
    "近畿スポーツランド",
    "モーターランド鈴鹿"
]