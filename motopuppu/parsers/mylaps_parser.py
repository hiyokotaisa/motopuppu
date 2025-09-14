# motopuppu/parsers/mylaps_parser.py
import csv
from .base_parser import BaseLapTimeParser

class MylapsParser(BaseLapTimeParser):
    def parse(self, file_stream) -> dict:
        laps = []
        reader = csv.reader(file_stream)
        
        data_started = False
        for i, row in enumerate(reader):
            if i >= self.MAX_LAPS:
                raise ValueError(f"ラップ数が多すぎます。最大{self.MAX_LAPS}ラップまでです。")

            if not row:
                continue

            try:
                lap_time_str = row[5].strip()
                if ':' in lap_time_str:
                    parts = lap_time_str.split(':')
                    normalized_lap_time = lap_time_str

                    if len(parts) == 3:
                        # H:M:S.f 形式を M:S.f 形式に変換
                        try:
                            h, m, s = int(parts[0]), int(parts[1]), parts[2]
                            total_minutes = h * 60 + m
                            # 小数点以下の秒と結合して、新しい形式の文字列を作成
                            normalized_lap_time = f"{total_minutes}:{s}"
                        except (ValueError, IndexError):
                            # 形式が不正な場合はスキップ
                            continue
                    
                    laps.append(normalized_lap_time)
            except IndexError:
                continue

        # GPSデータは存在しないため、空の辞書を返す
        return {'lap_times': laps, 'gps_tracks': {}}