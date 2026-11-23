# motopuppu/parsers/drogger_parser.py
import csv
from decimal import Decimal
from .base_parser import BaseLapTimeParser, open_text_stream


class DroggerParser(BaseLapTimeParser):
    """Droggerログを行単位で読み、確定したラップから順に返す。"""

    def parse(self, file_stream):
        return self.collect_laps(file_stream)

    def probe(self, file_stream) -> bool:
        with open_text_stream(file_stream) as stream:
            header = stream.readline(65536).lower()
            return all(column in header for column in ('lap', 'latitude', 'longitude'))

    def iter_laps(self, file_stream):
        with open_text_stream(file_stream) as stream:
            yield from self._iter_laps(csv.reader(stream))

    def _iter_laps(self, reader):
        header = next(reader, None)
        if not header:
            return
        columns = {name.lstrip('\ufeff').lower().strip(): i for i, name in enumerate(header)}
        if not all(name in columns for name in ('lap', 'latitude', 'longitude')):
            raise ValueError('CSVに必須列(Lap, Latitude, Longitude)が見つかりません。')

        def value(row, name):
            index = columns.get(name)
            return row[index].strip() if index is not None and index < len(row) else ''

        throttle_column = next(
            (name for name in ('throttolepos', 'throttlepos', 'throttle') if name in columns),
            'throttle',
        )
        optional_columns = (
            ('speed', 'speed', float),
            ('rpm', 'rpm', lambda raw: int(float(raw))),
            (throttle_column, 'throttle', float),
            ('runtime', 'runtime', float),
        )
        current_lap = None
        lap_time = None
        points = []
        lap_count = 0

        for row in reader:
            try:
                lap_number = int(float(value(row, 'lap')))
            except (ValueError, OverflowError):
                continue

            if current_lap is not None and lap_number != current_lap:
                if lap_number < current_lap:
                    raise ValueError('ラップ番号が逆順です。時系列順のCSVを使用してください。')
                if lap_time is not None:
                    lap_count += 1
                    if lap_count > self.MAX_LAPS:
                        raise ValueError(f'ラップ数が多すぎます。最大{self.MAX_LAPS}ラップまでです。')
                    yield lap_time, points
                # 次の周の読み込み前に、前の周の元データへの参照を手放す。
                points = []
                lap_time = None
            current_lap = lap_number

            if lap_time is None:
                try:
                    milliseconds = int(float(value(row, 'laptime')))
                    if milliseconds > 0:
                        seconds = Decimal(milliseconds) / 1000
                        lap_time = f'{int(seconds // 60)}:{seconds % 60:06.3f}'
                except (ValueError, OverflowError):
                    pass

            try:
                lat = float(value(row, 'latitude'))
                lng = float(value(row, 'longitude'))
            except ValueError:
                continue
            if lat == 0 and lng == 0:
                continue

            point = {'lat': lat, 'lng': lng}
            for source, target, convert in optional_columns:
                raw = value(row, source)
                if raw:
                    try:
                        point[target] = convert(raw)
                    except (ValueError, OverflowError):
                        pass
            points.append(point)

        if lap_time is not None:
            if lap_count >= self.MAX_LAPS:
                raise ValueError(f'ラップ数が多すぎます。最大{self.MAX_LAPS}ラップまでです。')
            yield lap_time, points
