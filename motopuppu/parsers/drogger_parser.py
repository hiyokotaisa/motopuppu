# motopuppu/parsers/drogger_parser.py
import csv
from decimal import Decimal, InvalidOperation
from .base_parser import BaseLapTimeParser

class DroggerParser(BaseLapTimeParser):
    """
    DroggerのCSVログファイルからラップタイムを抽出する、最終改善版パーサー
    """

    def parse(self, file_stream) -> list[str]:
        """
        DroggerのCSVを解析します。
        - 各ラップ番号が最初に出現した行を特定します。
        - その行の 'LapTime' 列にある整数値（ミリ秒）を読み取り、ラップタイムとして記録します。
        """
        laps = []
        # 処理済みのラップ番号を記録するためのセット
        processed_lap_numbers = set()
        
        try:
            reader = csv.DictReader(file_stream)
            if not reader.fieldnames:
                return []
        except Exception:
            return []

        # 'Lap' と 'LapTime' 列のヘッダー名を探します（大文字小文字を区別しない）
        fieldnames_lower = [f.lower() for f in reader.fieldnames]
        lap_col = 'lap'
        lap_time_col = 'laptime'

        if lap_col not in fieldnames_lower or lap_time_col not in fieldnames_lower:
            raise ValueError("CSVに 'Lap' または 'LapTime' 列が見つかりませんでした。")
        
        # 元のファイルでの正確なヘッダー名を取得
        lap_column_name = reader.fieldnames[fieldnames_lower.index(lap_col)]
        lap_time_column_name = reader.fieldnames[fieldnames_lower.index(lap_time_col)]

        for i, row in enumerate(reader):
            # 安全のため、最大ラップ数を超えた場合は処理を中断
            if len(laps) >= self.MAX_LAPS:
                break
            
            try:
                current_lap_str = row.get(lap_column_name, "").strip()
                if not current_lap_str:
                    continue
                
                current_lap_number = int(current_lap_str)

                # アウトラップなど、0未満のラップ番号は無視
                if current_lap_number < 1:
                    continue
                
                # このラップ番号がまだ処理されていない場合のみ、タイムを抽出する
                if current_lap_number not in processed_lap_numbers:
                    lap_milliseconds_str = row.get(lap_time_column_name, "0").strip()
                    lap_milliseconds = int(lap_milliseconds_str)
                    
                    if lap_milliseconds > 0:
                        # ミリ秒を秒に変換
                        lap_seconds = Decimal(lap_milliseconds) / 1000
                        
                        minutes = int(lap_seconds // 60)
                        seconds = lap_seconds % 60
                        
                        # "M:S.fff" 形式の文字列にフォーマット
                        formatted_time = f"{minutes}:{seconds:06.3f}"
                        laps.append(formatted_time)
                    
                    # このラップ番号を「処理済み」としてセットに追加
                    processed_lap_numbers.add(current_lap_number)

            except (ValueError, InvalidOperation, KeyError, IndexError):
                # 行に不正なデータがあった場合は安全にスキップ
                continue
        
        return laps