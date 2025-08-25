# motopuppu/parsers/drogger_parser.py
import csv
from decimal import Decimal, InvalidOperation
from .base_parser import BaseLapTimeParser
from collections import defaultdict

class DroggerParser(BaseLapTimeParser):
    """
    DroggerのCSVログファイルからラップタイムとGPS軌跡を抽出するパーサー
    """

    def parse(self, file_stream):
        """
        DroggerのCSVを解析し、ラップタイムとGPS軌跡データ（テレメトリー情報を含む）を返します。
        
        :return: {'lap_times': list[str], 'gps_tracks': dict} 形式の辞書
        """
        lap_times = []
        gps_tracks = defaultdict(list)
        processed_lap_numbers = set()
        
        try:
            # ファイルストリームの先頭に戻す (ストリームが再利用される可能性があるため)
            file_stream.seek(0)
            # BOM (Byte Order Mark) があるShift_JISファイルなどを考慮し、'utf-8-sig' を試す
            try:
                decoded_stream = [line.decode('utf-8-sig') for line in file_stream.readlines()]
            except UnicodeDecodeError:
                # utf-8-sigで失敗した場合、元のストリームを使いutf-8で再試行
                file_stream.seek(0)
                decoded_stream = [line.decode('utf-8') for line in file_stream.readlines()]
            
            reader = csv.DictReader(decoded_stream)
            if not reader.fieldnames:
                return {'lap_times': [], 'gps_tracks': {}}
        except Exception:
            # デコードや読み込みに失敗した場合
            return {'lap_times': [], 'gps_tracks': {}}

        # ヘッダー名を探します（大文字小文字を区別せず、スペースも無視）
        fieldnames_lower = {f.lower().strip(): f for f in reader.fieldnames}
        
        lap_col_name = fieldnames_lower.get('lap')
        lap_time_col_name = fieldnames_lower.get('laptime')
        lat_col_name = fieldnames_lower.get('latitude')
        lon_col_name = fieldnames_lower.get('longitude')
        speed_col_name = fieldnames_lower.get('speed')
        
        # ▼▼▼【ここから追記】テレメトリーデータの列名を取得 ▼▼▼
        runtime_col_name = fieldnames_lower.get('runtime')
        rpm_col_name = fieldnames_lower.get('rpm')
        throttle_col_name = fieldnames_lower.get('throttolepos') # CSVのヘッダー名に合わせる
        # ▲▲▲【追記はここまで】▲▲▲

        if not lap_col_name or not lap_time_col_name:
            raise ValueError("CSVに 'Lap' または 'LapTime' 列が見つかりませんでした。")
        
        has_gps_data = lat_col_name and lon_col_name

        for row in reader:
            try:
                current_lap_str = row.get(lap_col_name, "").strip()
                if not current_lap_str:
                    continue
                
                current_lap_number = int(float(current_lap_str))

                if current_lap_number < 1:
                    continue
                
                # GPSデータを記録
                if has_gps_data:
                    try:
                        lat = float(row[lat_col_name])
                        lng = float(row[lon_col_name])
                        # 緯度経度が0,0の場合は無効なデータとしてスキップ
                        if lat != 0 or lng != 0:
                            point_data = {'lat': lat, 'lng': lng}
                            # ▼▼▼【ここから修正】テレメトリー情報も一緒に記録 ▼▼▼
                            if speed_col_name:
                                try: point_data['speed'] = float(row[speed_col_name])
                                except (ValueError, TypeError, KeyError): pass
                            if runtime_col_name:
                                try: point_data['runtime'] = float(row[runtime_col_name])
                                except (ValueError, TypeError, KeyError): pass
                            if rpm_col_name:
                                try: point_data['rpm'] = int(float(row[rpm_col_name]))
                                except (ValueError, TypeError, KeyError): pass
                            if throttle_col_name:
                                try: point_data['throttle'] = float(row[throttle_col_name])
                                except (ValueError, TypeError, KeyError): pass
                            # ▲▲▲【修正はここまで】▲▲▲
                            gps_tracks[current_lap_number].append(point_data)
                    except (ValueError, TypeError, KeyError):
                        # GPSデータが不正な場合はスキップ
                        pass

                # このラップ番号がまだ処理されていない場合のみ、タイムを抽出
                if current_lap_number not in processed_lap_numbers:
                    if len(lap_times) >= self.MAX_LAPS:
                        continue

                    lap_milliseconds_str = row.get(lap_time_col_name, "0").strip()
                    lap_milliseconds = int(float(lap_milliseconds_str))
                    
                    if lap_milliseconds > 0:
                        lap_seconds = Decimal(lap_milliseconds) / 1000
                        minutes = int(lap_seconds // 60)
                        seconds = lap_seconds % 60
                        formatted_time = f"{minutes}:{seconds:06.3f}"
                        lap_times.append(formatted_time)
                    
                    processed_lap_numbers.add(current_lap_number)

            except (ValueError, InvalidOperation, KeyError, IndexError):
                continue
        
        return {'lap_times': lap_times, 'gps_tracks': dict(gps_tracks)}