# motopuppu/parsers/simple_csv_parser.py

from .base_parser import BaseLapTimeParser

class SimpleCsvParser(BaseLapTimeParser):
    """
    各行に1つのラップタイムが記録されたシンプルなCSV（またはTXT）ファイルをパースする。
    空行は無視する。
    """
    def parse(self, file_stream) -> list[str]:
        laps = []
        for i, line in enumerate(file_stream):
            if i >= self.MAX_LAPS:
                raise ValueError(f"ラップ数が多すぎます。最大{self.MAX_LAPS}ラップまでです。")
            
            lap_time = line.strip()
            if lap_time:  # 空行は無視
                laps.append(lap_time)
        
        return laps