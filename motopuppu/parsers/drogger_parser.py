# motopuppu/parsers/drogger_parser.py
import csv
from decimal import Decimal, InvalidOperation
from .base_parser import BaseLapTimeParser
from collections import defaultdict
import io

class DroggerParser(BaseLapTimeParser):
    """
    DroggerのCSVログファイルからラップタイムとGPS軌跡を抽出するパーサー
    必要なカラムのみを抽出し、メモリ使用量を抑える。
    """
    def parse(self, file_stream):
        # file_streamがバイナリモードの場合を想定
        file_stream.seek(0)
        try:
            # BOM付きUTF-8を考慮
            decoded_stream = [line.decode('utf-8-sig') for line in file_stream.readlines()]
        except UnicodeDecodeError:
            file_stream.seek(0)
            decoded_stream = [line.decode('utf-8', errors='replace') for line in file_stream.readlines()]
        
        return self._process_data(decoded_stream)

    def probe(self, file_stream) -> bool:
        file_stream.seek(0)
        try:
            # ヘッダー行を読んでDroggerらしさを判定
            header_line = file_stream.readline().decode('utf-8-sig').lower()
            # 最低限必要なカラムが含まれているか
            return 'lap' in header_line and 'latitude' in header_line and 'longitude' in header_line
        except (IOError, UnicodeDecodeError):
            try:
                file_stream.seek(0)
                header_line = file_stream.readline().decode('utf-8', errors='replace').lower()
                return 'lap' in header_line and 'latitude' in header_line
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

        # カラム名のマッピング（小文字化して正規化）
        field_map = {f.lower().strip(): f for f in reader.fieldnames}
        
        # 必須カラム
        col_lap = field_map.get('lap')
        col_time = field_map.get('laptime')
        col_lat = field_map.get('latitude')
        col_lon = field_map.get('longitude')
        
        # 取得するオプションカラム（これ以外は無視してメモリ節約）
        col_speed = field_map.get('speed')
        col_rpm = field_map.get('rpm')
        col_throttle = field_map.get('throttolepos') # DroggerのTypos対応
        if not col_throttle:
            col_throttle = field_map.get('throttlepos')
        if not col_throttle:
            col_throttle = field_map.get('throttle')
            
        col_runtime = field_map.get('runtime')

        if not col_lap or not col_lat or not col_lon:
            raise ValueError("CSVに必須列(Lap, Latitude, Longitude)が見つかりません。")
        
        current_lap_number = None

        for row in reader:
            try:
                lap_val = row.get(col_lap, "").strip()
                if not lap_val:
                    continue
                
                current_lap_number = int(float(lap_val))
                
                # GPSデータの抽出（必要な項目のみ辞書化）
                try:
                    lat = float(row[col_lat])
                    lng = float(row[col_lon])
                    
                    # 緯度経度が0でない場合のみ有効な点とする
                    if lat != 0 or lng != 0:
                        point_data = {'lat': lat, 'lng': lng}
                        
                        # 速度
                        if col_speed and row.get(col_speed):
                            try: point_data['speed'] = float(row[col_speed])
                            except: pass
                        
                        # 回転数 (整数化)
                        if col_rpm and row.get(col_rpm):
                            try: point_data['rpm'] = int(float(row[col_rpm]))
                            except: pass
                            
                        # スロットル
                        if col_throttle and row.get(col_throttle):
                            try: point_data['throttle'] = float(row[col_throttle])
                            except: pass
                            
                        # 経過時間
                        if col_runtime and row.get(col_runtime):
                            try: point_data['runtime'] = float(row[col_runtime])
                            except: pass

                        gps_tracks[current_lap_number].append(point_data)
                        
                except (ValueError, TypeError):
                    pass # 数値変換エラーの行はスキップ

                # ラップタイムの抽出
                # LapTimeカラムがあり、かつまだそのラップを処理していない場合
                if col_time and current_lap_number not in processed_lap_numbers:
                    if len(lap_times) >= self.MAX_LAPS:
                        continue

                    t_str = row.get(col_time, "0").strip()
                    try:
                        lap_ms = int(float(t_str))
                        if lap_ms > 0:
                            # ミリ秒 -> "M:SS.ms" 形式へ変換
                            lap_sec = Decimal(lap_ms) / 1000
                            mins = int(lap_sec // 60)
                            secs = lap_sec % 60
                            formatted_time = f"{mins}:{secs:06.3f}"
                            lap_times.append(formatted_time)
                            processed_lap_numbers.add(current_lap_number)
                    except:
                        pass

            except (ValueError, IndexError):
                continue
        
        # データの紐付けロジック
        # Droggerでは、Lap N の行に Lap N の走行データが入っている
        # しかし、LapTimeが記録されるのはそのラップの「最後」の行付近
        # motopuppuのDB構造では、ラップリストのindex 0 が 1周目 となる
        
        # 検出されたラップ番号（タイムが記録された周）をソート
        sorted_trigger_laps = sorted(list(processed_lap_numbers))
        
        final_gps_tracks = {}
        
        # タイム記録がある周について、その走行データを紐付ける
        for i, lap_time in enumerate(lap_times):
            if i < len(sorted_trigger_laps):
                target_lap_num = sorted_trigger_laps[i]
                
                # アプリ上のラップ番号 (1始まりの連番)
                app_lap_key = i + 1
                
                if target_lap_num in gps_tracks:
                    final_gps_tracks[app_lap_key] = gps_tracks[target_lap_num]
        
        # 補足: タイムが記録されなかった最終周（チェッカー後など）や
        # アウトラップ（Lap 0/-1）の扱いが必要な場合はここで調整するが、
        # 基本は「タイムが確定した周」を保存対象とする
        
        return {'lap_times': lap_times, 'gps_tracks': final_gps_tracks}