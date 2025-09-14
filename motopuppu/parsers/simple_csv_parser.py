# motopuppu/parsers/simple_csv_parser.py

from .base_parser import BaseLapTimeParser
from ..utils.lap_time_utils import is_valid_lap_time_format
import io

class SimpleCsvParser(BaseLapTimeParser):
    """
    各行に1つのラップタイムが記録されたシンプルなCSV（またはTXT）ファイルをパースする。
    空行は無視する。
    """
    def parse(self, file_stream) -> dict:
        # seek(0)を追加して、ストリームの読み取り位置をリセット
        if isinstance(file_stream, io.TextIOWrapper):
            file_stream.seek(0)

        laps = []
        for i, line in enumerate(file_stream):
            if i >= self.MAX_LAPS:
                raise ValueError(f"ラップ数が多すぎます。最大{self.MAX_LAPS}ラップまでです。")
            
            lap_time = line.strip()
            if lap_time:  # 空行は無視
                laps.append(lap_time)
        
        # GPSデータは存在しないため、空の辞書を返す
        return {'lap_times': laps, 'gps_tracks': {}}

    def probe(self, file_stream) -> bool:
        """
        ファイル冒頭の数行がラップタイム形式であるかを確認する。
        """
        # seek(0)を追加して、ストリームの読み取り位置をリセット
        if isinstance(file_stream, io.TextIOWrapper):
            file_stream.seek(0)
            
        lines_to_check = 5
        checked_lines = 0
        
        for line in file_stream:
            line_content = line.strip()
            if not line_content: # 空行はスキップ
                continue

            # 1行でもラップタイム形式でなければ、この形式ではないと判断
            if not is_valid_lap_time_format(line_content):
                return False
            
            checked_lines += 1
            if checked_lines >= lines_to_check:
                break
        
        # 1行以上チェックし、すべてがラップタイム形式であればTrue
        return checked_lines > 0