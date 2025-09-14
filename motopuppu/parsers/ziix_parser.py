# motopuppu/parsers/ziix_parser.py
import csv
from .base_parser import BaseLapTimeParser
import io

class ZiixParser(BaseLapTimeParser):
    def parse(self, file_stream) -> dict:
        if isinstance(file_stream, io.TextIOWrapper):
            file_stream.seek(0)
        
        laps = []
        reader = csv.reader(file_stream)
        try:
            next(reader)  # ヘッダー行 "LAP, LAP TIME,..." をスキップ
            next(reader)  # BEST行 "BEST,..." をスキップ
        except StopIteration:
            return {'lap_times': [], 'gps_tracks': {}} # 空ファイルの場合は空の辞書を返す

        for i, row in enumerate(reader):
            if i >= self.MAX_LAPS:
                raise ValueError(f"ラップ数が多すぎます。最大{self.MAX_LAPS}ラップまでです。")
            
            if not row or not row[0].strip().isdigit():
                continue
            
            try:
                raw_lap_time = row[1].strip()
                if raw_lap_time == "0'00.000":
                    continue
                lap_time_str = raw_lap_time.replace("'", ":", 1)
                laps.append(lap_time_str)
            except IndexError:
                continue
        
        return {'lap_times': laps, 'gps_tracks': {}}

    def probe(self, file_stream) -> bool:
        if isinstance(file_stream, io.TextIOWrapper):
            file_stream.seek(0)
            
        try:
            header_line = file_stream.readline().upper()
            return '"LAP"' in header_line and '"LAP TIME"' in header_line
        except (IOError, UnicodeDecodeError):
            return False