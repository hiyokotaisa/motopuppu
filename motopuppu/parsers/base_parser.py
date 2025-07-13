# motopuppu/parsers/base_parser.py
from abc import ABC, abstractmethod

class BaseLapTimeParser(ABC):
    """CSVパーサーの基底クラス"""
    MAX_LAPS = 5000 # 1セッションあたりの最大ラップ数

    @abstractmethod
    def parse(self, file_stream) -> list[str]:
        """
        ファイルストリームをパースし、ラップタイムの文字列リストを返す。
        例: ["1:41.878", "1:42.765"]
        """
        pass