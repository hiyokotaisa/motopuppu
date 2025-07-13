# motopuppu/parsers/ziix_parser.py
import csv
from .base_parser import BaseLapTimeParser

class ZiixParser(BaseLapTimeParser):
    def parse(self, file_stream) -> list[str]:
        laps = []
        reader = csv.reader(file_stream)
        try:
            next(reader)  # ヘッダー行 "LAP, LAP TIME,..." をスキップ
            next(reader)  # BEST行 "BEST,..." をスキップ
        except StopIteration:
            return [] # 空ファイルまたはヘッダーのみのファイル

        for i, row in enumerate(reader):
            if i >= self.MAX_LAPS:
                raise ValueError(f"ラップ数が多すぎます。最大{self.MAX_LAPS}ラップまでです。")
            
            if not row or not row[0].strip().isdigit():
                continue
            
            try:
                # ▼▼▼ ここから変更 ▼▼▼
                raw_lap_time = row[1].strip()

                # 0秒のラップタイムは無視する
                if raw_lap_time == "0'00.000":
                    continue
                # ▲▲▲ 変更ここまで ▲▲▲

                # '0'41.878' という形式を '0:41.878' に正規化
                lap_time_str = raw_lap_time.replace("'", ":", 1)
                laps.append(lap_time_str)
            except IndexError:
                # データが欠損している行は無視
                continue
        return laps