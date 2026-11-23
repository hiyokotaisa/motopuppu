# motopuppu/parsers/racechrono_parser.py
import csv
from .base_parser import BaseLapTimeParser, open_text_stream


class RaceChronoParser(BaseLapTimeParser):
    """RaceChrono v3 CSVを、1周分の元GPS点群だけを保持して解析する。"""

    def parse(self, file_stream):
        return self.collect_laps(file_stream)

    def probe(self, file_stream) -> bool:
        with open_text_stream(file_stream) as stream:
            # 形式推測のために巨大ファイル全体を読み込まない。
            content = stream.read(65536)
        if 'RaceChrono' in content and 'Format,3' in content:
            return True
        return any(
            all(column in line.lower() for column in ('timestamp', 'lap_number', 'elapsed_time', 'latitude'))
            for line in content.splitlines()[:30]
        )

    def iter_laps(self, file_stream):
        with open_text_stream(file_stream) as stream:
            yield from self._iter_laps(csv.reader(stream))

    def _iter_laps(self, reader):
        for row in reader:
            fields = [field.lstrip('\ufeff').strip().lower() for field in row]
            if all(name in fields for name in ('timestamp', 'latitude', 'lap_number')):
                break
        else:
            return

        try:
            col_lap = fields.index('lap_number')
            col_lat = fields.index('latitude')
            col_lon = fields.index('longitude')
            col_elapsed = fields.index('elapsed_time')
            col_speed = fields.index('speed')
        except ValueError:
            return

        current_lap = None
        points = []
        last_end_time = None
        lap_count = 0

        def finish_lap():
            end_time = points[-1]['runtime']
            start_time = points[0]['runtime'] if last_end_time is None else last_end_time
            seconds = end_time - start_time
            time_string = f'{int(seconds // 60)}:{seconds % 60:06.3f}' if seconds > 0 else None
            return time_string, end_time

        for row in reader:
            if len(row) < len(fields):
                continue
            try:
                lap_number = int(row[col_lap].strip())
                lat = float(row[col_lat])
                lng = float(row[col_lon])
                if lat == 0 and lng == 0:
                    continue
                speed = float(row[col_speed].strip() or '0') * 3.6
                runtime = float(row[col_elapsed].strip() or '0')
            except (ValueError, OverflowError):
                continue

            if current_lap is not None and lap_number != current_lap:
                if lap_number < current_lap:
                    raise ValueError('ラップ番号が逆順です。時系列順のCSVを使用してください。')
                lap_time, last_end_time = finish_lap()
                if lap_time is not None:
                    lap_count += 1
                    if lap_count > self.MAX_LAPS:
                        raise ValueError(f'ラップ数が多すぎます。最大{self.MAX_LAPS}ラップまでです。')
                    yield lap_time, points
                points = []
            current_lap = lap_number
            points.append({'lat': lat, 'lng': lng, 'speed': speed, 'runtime': runtime})

        if points:
            lap_time, _ = finish_lap()
            if lap_time is not None:
                if lap_count >= self.MAX_LAPS:
                    raise ValueError(f'ラップ数が多すぎます。最大{self.MAX_LAPS}ラップまでです。')
                yield lap_time, points
