# motopuppu/parsers/base_parser.py
from abc import ABC, abstractmethod
from contextlib import contextmanager
import io


@contextmanager
def open_text_stream(file_stream, encoding='utf-8-sig'):
    """全件を読み込まずにデコードし、呼び出し元のストリームは閉じない。"""
    file_stream.seek(0)
    if isinstance(file_stream, io.TextIOBase):
        yield file_stream
        return
    text_stream = io.TextIOWrapper(
        file_stream, encoding=encoding, errors='replace', newline=''
    )
    try:
        yield text_stream
    finally:
        text_stream.detach()


class BaseLapTimeParser(ABC):
    """CSVパーサーの基底クラス"""
    MAX_LAPS = 5000 # 1セッションあたりの最大ラップ数

    def iter_laps(self, file_stream):
        """(ラップタイム, GPS点群)を1周ずつ返す。GPSパーサーでは逐次解析する。"""
        parsed = self.parse(file_stream)
        tracks = parsed.get('gps_tracks', {})
        for lap_number, lap_time in enumerate(parsed.get('lap_times', []), 1):
            yield lap_time, tracks.get(lap_number, [])

    def collect_laps(self, file_stream):
        """既存のparse APIを利用する呼び出し元向けに結果をまとめる。"""
        lap_times = []
        gps_tracks = {}
        for lap_number, (lap_time, points) in enumerate(self.iter_laps(file_stream), 1):
            lap_times.append(lap_time)
            if points:
                gps_tracks[lap_number] = points
        return {'lap_times': lap_times, 'gps_tracks': gps_tracks}

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
