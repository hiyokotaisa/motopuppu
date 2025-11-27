# motopuppu/parsers/racechrono_parser.py
import csv
from collections import defaultdict
import io
from .base_parser import BaseLapTimeParser

class RaceChronoParser(BaseLapTimeParser):
    """
    RaceChrono (v3 CSV) ログファイルからラップタイムとGPS軌跡を抽出するパーサー
    """
    def parse(self, file_stream):
        # file_streamを先頭に戻す
        file_stream.seek(0)
        
        lines = []
        
        # 入力がテキストモード(TextIOWrapper)かバイナリモードかを判定して読み込む
        if isinstance(file_stream, io.TextIOWrapper):
            # テキストモードの場合、そのまま読み込む
            # BOM付きUTF-8の場合、先頭に \ufeff が残ることがあるため除去する
            raw_lines = file_stream.readlines()
            lines = [line.lstrip('\ufeff') for line in raw_lines]
        else:
            # バイナリモードの場合、デコード処理を行う
            try:
                # BOM付きUTF-8として読み込む
                lines = [line.decode('utf-8-sig') for line in file_stream.readlines()]
            except UnicodeDecodeError:
                file_stream.seek(0)
                # 失敗した場合はエラー無視でUTF-8読み込み
                lines = [line.decode('utf-8', errors='replace') for line in file_stream.readlines()]
            
        return self._process_data(lines)

    def probe(self, file_stream) -> bool:
        """
        ファイルヘッダーを読み込み、RaceChrono形式かどうかを判定する
        """
        file_stream.seek(0)
        try:
            # 最初の2KB程度を読んで判定
            content = file_stream.read(2048)
            
            # bytesならデコード、strならそのまま使う
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='ignore')
            
            # RaceChrono固有のメタデータチェック
            if 'RaceChrono' in content and 'Format,3' in content:
                return True

            # ヘッダー列構造による判定 (メタデータがない場合などの保険)
            # read()した後なのでseekしなおす
            file_stream.seek(0)
            lines = file_stream.readlines()
            # linesがbytesのリストかstrのリストか確認して処理
            for line in lines[:30]: 
                if isinstance(line, bytes):
                    l = line.decode('utf-8', errors='ignore').lower()
                else:
                    l = line.lower()
                
                # RaceChrono v3の典型的な必須カラム構成
                if 'timestamp' in l and 'lap_number' in l and 'elapsed_time' in l and 'latitude' in l:
                    return True
            return False
        except Exception:
            return False

    def _process_data(self, lines):
        # ヘッダー行を探す
        header_index = -1
        for i, line in enumerate(lines):
            l = line.lower()
            if 'timestamp' in l and 'latitude' in l and 'lap_number' in l:
                header_index = i
                break
        
        if header_index == -1:
             return {'lap_times': [], 'gps_tracks': {}}

        # ヘッダー行の解析
        header_line = lines[header_index].strip()
        # カラム名のリスト作成（小文字化して正規化）
        fieldnames = [f.strip().lower() for f in header_line.split(',')]
        
        # 必須カラムのインデックス特定
        try:
            col_lap = fieldnames.index('lap_number')
            col_lat = fieldnames.index('latitude')
            col_lon = fieldnames.index('longitude')
            col_elapsed = fieldnames.index('elapsed_time')
            
            # 速度: 複数ある場合は最初のもの(通常GPS速度)を採用
            # RaceChronoには 'speed' カラムが複数ある場合がある (GPS速度, OBD速度など)
            # list.index('speed') は最初に見つかったインデックス(通常左側)を返す
            col_speed = fieldnames.index('speed')
        except ValueError:
            # 必須カラム不足の場合は空を返す
             return {'lap_times': [], 'gps_tracks': {}}

        # データ開始行（ヘッダー + 単位行 + デバイス行 + etc の次から）
        data_start_index = header_index + 1

        # データをラップ番号ごとにグルーピング
        # lap_number -> list of dict
        laps_data = defaultdict(list)
        
        for line in lines[data_start_index:]:
            if not line.strip(): continue
            parts = line.split(',')
            
            # 列数が足りない行はスキップ
            if len(parts) < len(fieldnames): continue
            
            try:
                # ラップ番号の取得
                lap_val_str = parts[col_lap].strip()
                if not lap_val_str:
                    continue
                
                lap_num = int(lap_val_str)
                
                # GPS座標
                lat_str = parts[col_lat].strip()
                lng_str = parts[col_lon].strip()
                
                if not lat_str or not lng_str: continue

                lat = float(lat_str)
                lng = float(lng_str)
                
                # 緯度経度が0の無効データは除外
                if lat == 0 and lng == 0: continue
                
                # 速度 (m/s -> km/h 変換)
                speed_str = parts[col_speed].strip() if parts[col_speed] else "0"
                speed_ms = float(speed_str) if speed_str else 0.0
                speed_kmh = speed_ms * 3.6
                
                # 経過時間 (セッション開始からの秒数)
                elapsed_str = parts[col_elapsed].strip() if parts[col_elapsed] else "0"
                elapsed = float(elapsed_str) if elapsed_str else 0.0
                
                point_data = {
                    'lat': lat,
                    'lng': lng,
                    'speed': speed_kmh,
                    'runtime': elapsed
                }
                
                laps_data[lap_num].append(point_data)
                
            except (ValueError, IndexError):
                # 数値変換エラー（単位行やデバイス名行など）は安全にスキップ
                continue
        
        # 結果データの構築
        final_lap_times = []
        final_gps_tracks = {}
        
        # ラップ番号順に処理
        sorted_lap_nums = sorted(laps_data.keys())
        
        # 前のラップの終了時間（初期値）
        last_lap_end_time = 0.0
        
        # 計測ラップ (1以上) の処理
        for i, lap_num in enumerate(sorted_lap_nums):
            points = laps_data[lap_num]
            if not points: continue
            
            # このラップの終了時間
            current_lap_end_time = points[-1]['runtime']
            
            # 初回ラップの場合の開始時間補正
            if i == 0 and last_lap_end_time == 0.0:
                 last_lap_end_time = points[0]['runtime']

            lap_time_sec = current_lap_end_time - last_lap_end_time
            
            if lap_time_sec > 0:
                # 文字列形式 "M:SS.ms" に変換
                mins = int(lap_time_sec // 60)
                secs = lap_time_sec % 60
                formatted_time = f"{mins}:{secs:06.3f}"
                
                final_lap_times.append(formatted_time)
                
                # アプリケーション用のラップインデックス (1, 2, 3...)
                app_lap_index = len(final_lap_times)
                final_gps_tracks[app_lap_index] = points
            
            last_lap_end_time = current_lap_end_time
            
        return {'lap_times': final_lap_times, 'gps_tracks': final_gps_tracks}