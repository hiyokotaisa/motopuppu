# motopuppu/parsers/base_parser.py
from abc import ABC, abstractmethod

class BaseLapTimeParser(ABC):
    """CSVパーサーの基底クラス"""
    MAX_LAPS = 5000 # 1セッションあたりの最大ラップ数

    @abstractmethod
    def parse(self, file_stream) -> dict:
        """
        ファイルストリームをパースし、ラップタイムとGPS軌跡を含む辞書を返す。
        例: {'lap_times': ["1:41.878"], 'gps_tracks': {1: [{'lat':..., 'lng':...}]}}
        """
        pass

    @abstractmethod
    def probe(self, file_stream) -> bool:
        """
        ファイルストリームがこのパーサーの形式と一致するかどうかを簡易的に判定する。
        ヘッダーや最初の数行をチェックし、True/Falseを返す。
        """
        pass