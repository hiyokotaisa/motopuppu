# motopuppu/parsers/drogger_parser.py
import csv
from decimal import Decimal, InvalidOperation
from .base_parser import BaseLapTimeParser
from collections import defaultdict
import io

class DroggerParser(BaseLapTimeParser):
    """
    DroggerのCSVログファイルからラップタイムとGPS軌跡を抽出するパーサー
    """
    def parse(self, file_stream):
        # file_streamがバイナリモードの場合を想定
        file_stream.seek(0)
        try:
            decoded_stream = [line.decode('utf-8-sig') for line in file_stream.readlines()]
        except UnicodeDecodeError:
            file_stream.seek(0)
            decoded_stream = [line.decode('utf-8') for line in file_stream.readlines()]
        
        return self._process_data(decoded_stream)

    def probe(self, file_stream) -> bool:
        file_stream.seek(0)
        try:
            # BOMを考慮してutf-8-sigでデコード
            header_line = file_stream.readline().decode('utf-8-sig').lower()
            return 'laptime' in header_line and 'latitude' in header_line and 'longitude' in header_line
        except (IOError, UnicodeDecodeError):
            # デコードに失敗した場合は再度試す
            try:
                file_stream.seek(0)
                header_line = file_stream.readline().decode('utf-8').lower()
                return 'laptime' in header_line and 'latitude' in header_line and 'longitude' in header_line
            except:
                return False
    
    def _process_data(self, decoded_stream):
        lap_times = []
        gps_tracks = defaultdict(list)
        processed_lap_numbers = set()
        
        try:
            reader = csv.DictReader(decoded_stream)
            if not reader.fieldnames:
                return {'lap_times': [], 'gps_tracks': {}}
        except Exception:
            return {'lap_times': [], 'gps_tracks': {}}

        fieldnames_lower = {f.lower().strip(): f for f in reader.fieldnames}
        lap_col_name = fieldnames_lower.get('lap')
        lap_time_col_name = fieldnames_lower.get('laptime')
        lat_col_name = fieldnames_lower.get('latitude')
        lon_col_name = fieldnames_lower.get('longitude')
        speed_col_name = fieldnames_lower.get('speed')
        runtime_col_name = fieldnames_lower.get('runtime')
        rpm_col_name = fieldnames_lower.get('rpm')
        throttle_col_name = fieldnames_lower.get('throttolepos')

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
                
                if has_gps_data:
                    try:
                        lat = float(row[lat_col_name])
                        lng = float(row[lon_col_name])
                        if lat != 0 or lng != 0:
                            point_data = {'lat': lat, 'lng': lng}
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
                            gps_tracks[current_lap_number].append(point_data)
                    except (ValueError, TypeError, KeyError):
                        pass

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
        
        # ▼▼▼ 変更箇所（ここから） ▼▼▼
        # タイムが記録されたラップ（例：2, 3, ..., 11）を昇順にソート
        # これが実際の軌跡データが含まれるラップ番号のリストになる
        sorted_track_lap_numbers = sorted(list(processed_lap_numbers))
        
        final_gps_tracks = {}
        # 収集したラップタイムの数だけループを回す
        for i, lap_time in enumerate(lap_times):
            # 新しいキーは 1 から始まる連番 (1, 2, 3...)
            new_lap_key = i + 1
            
            # sorted_track_lap_numbersがlap_timesより短い場合に対応
            if i < len(sorted_track_lap_numbers):
                # 対応する元の軌跡データが格納されているキーを取得
                # (i=0 のとき、sorted_track_lap_numbers[0] は 2 になる)
                original_track_key = sorted_track_lap_numbers[i]
                
                # 新しいキーで、正しい軌跡データを格納し直す
                if original_track_key in gps_tracks:
                    final_gps_tracks[new_lap_key] = gps_tracks[original_track_key]
        # ▲▲▲ 変更箇所（ここまで） ▲▲▲
        
        return {'lap_times': lap_times, 'gps_tracks': final_gps_tracks}