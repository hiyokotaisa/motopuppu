# motopuppu/parsers/mylaps_parser.py
import csv
from .base_parser import BaseLapTimeParser
import io
import re

class MylapsParser(BaseLapTimeParser):
    def parse(self, file_stream) -> dict:
        if isinstance(file_stream, io.TextIOWrapper):
            file_stream.seek(0)

        laps = []
        reader = csv.reader(file_stream)
        
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
                        try:
                            h, m, s = int(parts[0]), int(parts[1]), parts[2]
                            total_minutes = h * 60 + m
                            normalized_lap_time = f"{total_minutes}:{s}"
                        except (ValueError, IndexError):
                            continue
                    laps.append(normalized_lap_time)
            except IndexError:
                continue

        return {'lap_times': laps, 'gps_tracks': {}}

    def probe(self, file_stream) -> bool:
        if isinstance(file_stream, io.TextIOWrapper):
            file_stream.seek(0)
            
        reader = csv.reader(file_stream)
        checked_rows = 0
        
        # 最初の10行をチェック
        for i, row in enumerate(reader):
            if i > 10: break
            if len(row) > 5:
                # 6列目のデータが "数字:数字.数字" の形式に一致するか
                if re.match(r"^\d{1,3}:\d{2}\.\d+$", row[5].strip()):
                    checked_rows += 1
        
        # 2行以上一致すればMYLAPS形式と判断
        return checked_rows >= 2