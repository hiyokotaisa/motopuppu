# motopuppu/utils/lap_time_utils.py
import re
import statistics
from decimal import Decimal

def get_rank_suffix(rank: int) -> str:
    """順位に応じた英語の接尾辞 (st, nd, rd, th) を返す"""
    if not isinstance(rank, int) or rank <= 0:
        return ""
    if 11 <= (rank % 100) <= 13:
        return "th"
    last_digit = rank % 10
    if last_digit == 1:
        return "st"
    if last_digit == 2:
        return "nd"
    if last_digit == 3:
        return "rd"
    return "th"

def parse_time_to_seconds(time_str):
    """ "M:S.f" または "S.f" 形式の文字列を秒(Decimal)に変換 """
    if not isinstance(time_str, str): return None
    try:
        # ZiiXの M'S.f 形式も考慮
        time_str = time_str.replace("'", ":")
        parts = time_str.split(':')
        if len(parts) == 2:
            # M:S.f 形式
            minutes = Decimal(parts[0])
            seconds = Decimal(parts[1])
            return minutes * 60 + seconds
        else:
            # S.f 形式
            return Decimal(parts[0])
    except:
        return None

def format_seconds_to_time(total_seconds):
    """ 秒(Decimal)を "M:SS.fff" 形式の文字列に変換 """
    if total_seconds is None: return "N/A"
    total_seconds = Decimal(total_seconds)
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:06.3f}" # 0埋めして S.fff 形式にする

# --- ▼▼▼ ここからが修正箇所 ▼▼▼ ---
def calculate_lap_stats(lap_times, sort_by='record_asc'):
    """
    ラップタイムのリストからベスト、平均、各ラップの詳細を計算する。
    sort_by パラメータに応じて結果のリストをソートする。
    """
    if not lap_times or not isinstance(lap_times, list):
        return "N/A", "N/A", []

    # 1. 元のインデックスを保持したまま、有効なラップタイム（秒）のリストを作成
    lap_seconds_indexed = []
    for i, t in enumerate(lap_times):
        sec = parse_time_to_seconds(t)
        if sec is not None and sec > 0:
            lap_seconds_indexed.append({'original_index': i, 'seconds': sec})

    if not lap_seconds_indexed:
        return "N/A", "N/A", []

    # 2. 統計計算のために秒のみのリストも用意
    valid_seconds = [item['seconds'] for item in lap_seconds_indexed]
    best_lap_sec = min(valid_seconds)
    average_lap_sec = sum(valid_seconds) / len(valid_seconds)

    # 3. タイム順にソートして順位を決定
    sorted_by_time = sorted(lap_seconds_indexed, key=lambda x: x['seconds'])
    rank_map = {}
    for rank, item in enumerate(sorted_by_time, 1):
        rank_map[item['original_index']] = rank

    # 4. 最終的な詳細リストを作成 (この時点では記録順)
    lap_details = []
    for item in sorted(lap_seconds_indexed, key=lambda x: x['original_index']):
        original_index = item['original_index']
        sec = item['seconds']
        rank = rank_map.get(original_index)

        gap_str = ""
        if sec != best_lap_sec:
            diff = sec - best_lap_sec
            suffix = get_rank_suffix(rank)
            gap_str = f"+{diff:.3f} ({rank}{suffix})"

        lap_details.append({
            'lap_num': original_index + 1,
            'time_str': format_seconds_to_time(sec),
            'diff_str': gap_str,
            'is_best': sec == best_lap_sec,
            'seconds': sec  # ソート用に秒数を保持
        })

    # 5. `sort_by` の値に応じてリストを並び替え
    if sort_by == 'time_asc':
        lap_details.sort(key=lambda x: x['seconds'])
    elif sort_by == 'time_desc':
        lap_details.sort(key=lambda x: x['seconds'], reverse=True)
    # 'record_asc' の場合は何もしないので、デフォルトの記録順になる

    return format_seconds_to_time(best_lap_sec), format_seconds_to_time(average_lap_sec), lap_details
# --- ▲▲▲ 変更ここまで ▲▲▲ ---

def _calculate_and_set_best_lap(session, lap_times_list):
    """
    ラップタイムのリストからベストラップを秒で計算し、
    セッションオブジェクトにセットする
    """
    if not lap_times_list:
        session.best_lap_seconds = None
        return
    
    lap_seconds = [s for s in (parse_time_to_seconds(t) for t in lap_times_list) if s is not None]
    
    if lap_seconds:
        session.best_lap_seconds = min(lap_seconds)
    else:
        session.best_lap_seconds = None

def filter_outlier_laps(lap_times_list: list, threshold_multiplier: float = 2.0) -> list:
    """
    ラップタイムのリストから外れ値（極端に遅いラップ）を除外する。
    中央値の threshold_multiplier 倍より遅いラップを外れ値とみなす。
    """
    if not lap_times_list or len(lap_times_list) < 3:
        return lap_times_list # データが少ない場合は何もしない

    # 文字列のラップタイムをDecimalの秒に変換
    lap_seconds = [s for s in (parse_time_to_seconds(t) for t in lap_times_list) if s is not None and s > 0]
    if not lap_seconds:
        return []

    # 中央値を計算
    median_lap = statistics.median(lap_seconds)
    
    # 閾値を設定 (中央値の N 倍)
    threshold = median_lap * Decimal(str(threshold_multiplier))

    # 閾値を超えないラップタイムのみをフィルタリング
    # 元の文字列リストのインデックスと秒リストのインデックスは一致すると仮定
    filtered_laps = [
        lap_str for lap_str, lap_sec in zip(lap_times_list, lap_seconds) if lap_sec <= threshold
    ]
    
    return filtered_laps

def is_valid_lap_time_format(s: str) -> bool:
    """
    文字列が '分:秒.ミリ秒' または '秒.ミリ秒' の形式かチェックする。
    例: '1:23.456', '83.456', '1:23', '83'
    """
    if not isinstance(s, str):
        return False
    # 正規表現パターン: (任意で[数字とコロン]) + [数字] + (任意で[ドットと数字])
    # これにより "M:S.f" と "S.f" の両方の形式にマッチする
    pattern = re.compile(r'^(\d+:)?\d+(\.\d+)?$')
    return bool(pattern.match(s))