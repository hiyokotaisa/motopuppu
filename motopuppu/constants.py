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
    "chain": {
        "title": "チェーン",
        "keys": {
            "chain_brand": "チェーン銘柄",
            "chain_size": "チェーンサイズ",
            "chain_links": "リンク数"
        }
    },
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
    "tire_front": {
        "title": "タイヤ (フロント)",
        "keys": {
            "tire_brand": "タイヤ銘柄",
            "tire_compound": "コンパウンド",
            "tire_pressure_cold_kpa": "空気圧(冷間)",
            "tire_pressure_hot_kpa": "空気圧(温間)",
            "tire_size": "サイズ"
        }
    },
    "tire_rear": {
        "title": "タイヤ (リア)",
        "keys": {
            "tire_brand": "タイヤ銘柄",
            "tire_compound": "コンパウンド",
            "tire_pressure_cold_kpa": "空気圧(冷間)",
            "tire_pressure_hot_kpa": "空気圧(温間)",
            "tire_size": "サイズ"
        }
    },
    "tire": {
        "title": "タイヤ (旧データ)",
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
    },
    "brake": {
        "title": "ブレーキ",
        "keys": {
            "front_pad": "F: パッド銘柄",
            "rear_pad": "R: パッド銘柄",
            "master_cylinder": "マスターシリンダー",
            "lever_position": "レバー位置"
        }
    },
    "position": {
        "title": "ポジション",
        "keys": {
            "handlebar": "ハンドル位置/角度",
            "step_position": "ステップ位置",
            "seat_height": "シート高"
        }
    }
}


# --- Forms 関連 ---

# スタンド名の候補リスト (FuelForm用)
GAS_STATION_BRANDS = [
    'ENEOS', '出光興産/apollostation', 'コスモ石油', 'キグナス石油', 'JA-SS', 'SOLATO',
]

# 日本の二輪走行可能サーキットリスト（地方別）
CIRCUITS_BY_REGION = {
    "北海道・東北": [
        "十勝スピードウェイ",
        "スポーツランドSUGO",
        "エビスサーキット東コース",
        "エビスサーキット西コース",
    ],
    "関東": [
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
    ],
    "中部・東海": [
        "富士スピードウェイ 本コース",
        "富士スピードウェイ ショートコース",
        "富士スピードウェイ カートコース",
        "白糸スピードランド",
        "スパ西浦モーターパーク",
        "モーターランド三河",
        "YZサーキット東コース",
        "鈴鹿ツインサーキット",
        "モーターランド鈴鹿",
    ],
    "近畿": [
        "鈴鹿サーキット フルコース",
        "鈴鹿サーキット 南コース",
        "近畿スポーツランド",
        "レインボースポーツ カートコース",
        "セントラルサーキット",
        "岡山国際サーキット",
    ],
    "中国・四国": [
        "TSタカタサーキット",
        "瀬戸内海サーキット",
    ],
    "九州・沖縄": [
        "オートポリス",
        "HSR九州",
    ]
}

# 従来の `JAPANESE_CIRCUITS` という名前でフラットなリストも定義する
JAPANESE_CIRCUITS = [circuit for region_circuits in CIRCUITS_BY_REGION.values() for circuit in region_circuits]

# ▼▼▼【修正】サーキットのメタデータ (short_nameを削除) ▼▼▼
CIRCUIT_METADATA = {
    "筑波サーキット TC2000": {
        "lat": 36.1533, "lng": 139.9208,
        "url": "https://www.tsukuba-circuit.jp/"
    },
    "筑波サーキット TC1000": {
        "lat": 36.1522, "lng": 139.9220,
        "url": "https://www.tsukuba-circuit.jp/"
    },
    "ツインリンクもてぎ ロードコース": {
        "lat": 36.5333, "lng": 140.2274,
        "url": "https://www.mr-motegi.jp/"
    },
    "袖ヶ浦フォレストレースウェイ": {
        "lat": 35.4056, "lng": 140.1130,
        "url": "http://www.sodegaura-forest-raceway.com/"
    },
    "桶川スポーツランド ロングコース": {
        "lat": 35.9866, "lng": 139.5445,
        "url": "https://okspo.jp/"
    },
    "桶川スポーツランド ミドルコース": {
        "lat": 35.9866, "lng": 139.5445,
        "url": "https://okspo.jp/"
    },
    "桶川スポーツランド ショートコース": {
        "lat": 35.9866, "lng": 139.5445,
        "url": "https://okspo.jp/"
    },
    "富士スピードウェイ 本コース": {
        "lat": 35.3705, "lng": 138.9272,
        "url": "https://www.fsw.tv/"
    },
    "鈴鹿サーキット フルコース": {
        "lat": 34.8431, "lng": 136.5408,
        "url": "https://www.suzukacircuit.jp/"
    },
    "井頭モーターパーク": {
        "lat": 36.4360, "lng": 139.9920,
        "url": "https://www.linson.co.jp/"
    },
    "茂原ツインサーキット ショートコース(西)": {
        "lat": 35.3821, "lng": 140.2811,
        "url": "http://www.mobara-tc.com/"
    },
    "茂原ツインサーキット ロングコース(東)": {
        "lat": 35.3821, "lng": 140.2811,
        "url": "http://www.mobara-tc.com/"
    },
    "白糸スピードランド": {
        "lat": 35.3095, "lng": 138.5878,
        "url": "https://www.shiraito-speedland.co.jp/"
    },
    "スパ西浦モーターパーク": {
        "lat": 34.7748, "lng": 137.1865,
        "url": "http://www.itoracing.co.jp/snmp/"
    },
    "レインボースポーツ カートコース": {
        "lat": 35.1025, "lng": 136.6439,
        "url": "https://www.rainbowsports.jp/"
    },
    "近畿スポーツランド": {
        "lat": 34.8708, "lng": 135.8519,
        "url": "http://www.kinspo.jp/"
    },
    "モーターランド鈴鹿": {
        "lat": 34.8072, "lng": 136.5052,
        "url": "http://www.motorlandsuzuka.com/"
    },
}


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
# リーダーボードの対象サーキットを限定するためのリスト
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