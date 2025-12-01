# motopuppu/views/circuit_dashboard.py
import decimal
import requests
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, current_app, url_for, request, flash, redirect
from flask_login import login_required, current_user
from sqlalchemy import func, case, or_, desc
from sqlalchemy.orm import aliased, joinedload

from ..models import db, ActivityLog, SessionLog, User, Motorcycle, UserCircuitTarget, TrackSchedule
from ..constants import CIRCUIT_METADATA
from ..utils.lap_time_utils import format_seconds_to_time, parse_time_to_seconds
from ..forms import TargetLapTimeForm

circuit_dashboard_bp = Blueprint(
    'circuit_dashboard',
    __name__,
    template_folder='../../templates',
    url_prefix='/circuit-dashboard'
)

def get_leaderboard_rankings(circuit_name, user_id):
    """ 指定されたサーキットのリーダーボード情報を取得し、
        指定されたユーザーの順位と次の順位との差を返す """
        
    subquery = db.session.query(
        SessionLog.id.label('session_id'),
        ActivityLog.user_id,
        SessionLog.best_lap_seconds,
        func.row_number().over(
            partition_by=(ActivityLog.user_id, ActivityLog.motorcycle_id),
            order_by=SessionLog.best_lap_seconds.asc()
        ).label('rn')
    ).join(ActivityLog, SessionLog.activity_log_id == ActivityLog.id)\
     .filter(
        ActivityLog.circuit_name == circuit_name,
        SessionLog.include_in_leaderboard == True,
        SessionLog.best_lap_seconds.isnot(None)
    ).subquery()

    best_laps = db.session.query(
        subquery.c.user_id,
        subquery.c.best_lap_seconds,
    ).filter(subquery.c.rn == 1)\
     .order_by(subquery.c.best_lap_seconds.asc())\
     .all()

    user_rank = None
    user_best_lap = None
    next_rank_lap = None

    for i, row in enumerate(best_laps):
        if row.user_id == user_id:
            user_rank = i + 1
            user_best_lap = row.best_lap_seconds
            # 自分の1つ前の順位の人のタイムを取得
            if i > 0:
                next_rank_lap = best_laps[i-1].best_lap_seconds
            break
            
    gap = None
    if user_best_lap and next_rank_lap:
        gap = user_best_lap - next_rank_lap

    return {
        'rank': user_rank,
        'gap_to_next': gap
    }

@circuit_dashboard_bp.route('/')
@login_required
def index():
    """ サーキットダッシュボードのメインページ """
    
    # ユーザーの全セッションログから、サーキット名が存在するものだけを対象にする
    base_query = db.session.query(
        ActivityLog, SessionLog
    ).join(
        SessionLog, ActivityLog.id == SessionLog.activity_log_id
    ).filter(
        ActivityLog.user_id == current_user.id,
        ActivityLog.circuit_name.isnot(None),
        SessionLog.best_lap_seconds.isnot(None)
    )

    # 1. サーキットごとの自己ベストセッションを取得
    subq = base_query.with_entities(
        ActivityLog.circuit_name,
        SessionLog.id.label('session_id'),
        func.row_number().over(
            partition_by=ActivityLog.circuit_name,
            order_by=SessionLog.best_lap_seconds.asc()
        ).label('rn')
    ).subquery()

    # 目標タイムを取得するために LEFT JOIN を行う
    best_sessions_with_targets_query = db.session.query(
        subq.c.session_id,
        subq.c.circuit_name,
        UserCircuitTarget.target_lap_seconds
    ).select_from(subq).outerjoin(
        UserCircuitTarget,
        (UserCircuitTarget.user_id == current_user.id) &
        (UserCircuitTarget.circuit_name == subq.c.circuit_name)
    ).filter(subq.c.rn == 1).all()
    
    best_session_ids_list = [sid for sid, cname, target in best_sessions_with_targets_query]
    
    targets_map = {
        cname: target for sid, cname, target in best_sessions_with_targets_query
    }
    
    best_sessions = db.session.query(SessionLog).options(
        joinedload(SessionLog.activity).joinedload(ActivityLog.motorcycle),
        joinedload(SessionLog.setting_sheet)
    ).filter(
        SessionLog.id.in_(best_session_ids_list)
    ).all()
    
    # 2. ダッシュボードに表示するデータを整形
    circuit_data = []
    
    # グラフ用データ取得のために全データを取得（N+1回避のためeager load）
    all_sessions_for_graph = base_query.options(
        joinedload(SessionLog.activity)
    ).order_by(ActivityLog.activity_date.asc()).all()

    today = date.today()
    next_week = today + timedelta(days=7)

    for best_session in best_sessions:
        circuit_name = best_session.activity.circuit_name
        
        # 2a. 車両ごとのベストラップと統計を取得
        best_session_id_subq = db.session.query(
            ActivityLog.motorcycle_id,
            func.first_value(SessionLog.id).over(
                partition_by=ActivityLog.motorcycle_id,
                order_by=SessionLog.best_lap_seconds.asc()
            ).label('best_session_id')
        ).join(SessionLog, ActivityLog.id == SessionLog.activity_log_id)\
         .filter(
            ActivityLog.user_id == current_user.id,
            ActivityLog.circuit_name == circuit_name,
            SessionLog.best_lap_seconds.isnot(None)
        ).distinct().subquery()

        vehicle_breakdown_query = db.session.query(
            Motorcycle.id.label('motorcycle_id'),
            Motorcycle.name.label('motorcycle_name'),
            func.min(SessionLog.best_lap_seconds).label('vehicle_best_lap'),
            func.count(SessionLog.id).label('session_count'),
            best_session_id_subq.c.best_session_id
        ).join(
            ActivityLog, SessionLog.activity_log_id == ActivityLog.id
        ).join(
            Motorcycle, ActivityLog.motorcycle_id == Motorcycle.id
        ).join(
            best_session_id_subq, Motorcycle.id == best_session_id_subq.c.motorcycle_id
        ).filter(
            ActivityLog.user_id == current_user.id,
            ActivityLog.circuit_name == circuit_name,
            SessionLog.best_lap_seconds.isnot(None)
        ).group_by(
            Motorcycle.id, 
            Motorcycle.name,
            best_session_id_subq.c.best_session_id
        ).order_by(
            func.min(SessionLog.best_lap_seconds).asc()
        ).all()
        
        vehicle_data = []
        user_personal_best = best_session.best_lap_seconds
        for row in vehicle_breakdown_query:
            gap = row.vehicle_best_lap - user_personal_best if user_personal_best else None
            vehicle_data.append({
                'id': row.motorcycle_id,
                'name': row.motorcycle_name,
                'best_lap': row.vehicle_best_lap,
                'session_count': row.session_count,
                'gap_to_pb': gap,
                'is_pb_holder': abs(gap) < decimal.Decimal('0.0001') if gap is not None else False,
                'best_session_id': row.best_session_id
            })
        
        # 2b. ラップタイム推移グラフ（スパークライン）のデータを作成
        chart_data = {
            'labels': [], # 日付
            'data': []   # ベストラップ
        }
        for activity, session in all_sessions_for_graph:
            if activity.circuit_name == circuit_name:
                chart_data['labels'].append(activity.activity_date.isoformat())
                chart_data['data'].append(float(session.best_lap_seconds))

        # 2c. リーダーボード情報を取得
        leaderboard_info = get_leaderboard_rankings(circuit_name, current_user.id)
        
        # 2d. 最新セッションを取得 (直近の調子判定用)
        latest_session_row = base_query.filter(
            ActivityLog.circuit_name == circuit_name
        ).order_by(ActivityLog.activity_date.desc(), SessionLog.id.desc()).first()
        
        latest_session_obj = latest_session_row.SessionLog if latest_session_row else None
        
        # ログ作成リンク用の車両IDを取得 (最新セッションの車両、またはデフォルト車両)
        latest_vehicle_id = None
        if latest_session_obj:
            latest_vehicle_id = latest_session_obj.activity.motorcycle_id
        elif vehicle_data:
            latest_vehicle_id = vehicle_data[0]['id'] # データがあれば最初の車両
        else:
            first_bike = Motorcycle.query.filter_by(user_id=current_user.id).first()
            if first_bike:
                latest_vehicle_id = first_bike.id

        # 目標タイムとフォームをデータに追加
        target_lap_seconds = targets_map.get(circuit_name)
        form = TargetLapTimeForm()
        if target_lap_seconds:
            form.target_time.data = format_seconds_to_time(target_lap_seconds)

        # メタデータと走行枠情報の取得
        metadata = CIRCUIT_METADATA.get(circuit_name, {})
        
        # スケジュール取得 (1週間分)
        raw_schedules = TrackSchedule.query.filter(
            TrackSchedule.date >= today,
            TrackSchedule.date <= next_week,
            or_(
                TrackSchedule.circuit_name == circuit_name,
                TrackSchedule.circuit_name.contains(circuit_name)
            )
        ).order_by(TrackSchedule.date.asc(), TrackSchedule.start_time.asc()).all()
        
        # ▼▼▼【修正】スケジュール集計ロジック（走行枠の内訳分析を追加）▼▼▼
        # 日付ごとにデータをまとめる一時辞書
        daily_slots = {}
        
        for s in raw_schedules:
            if s.date not in daily_slots:
                daily_slots[s.date] = {
                    'date': s.date,
                    'titles': set(), # 枠名を重複なしで収集 (例: ミニバイク①, 大型バイク①)
                    'circuit_name': s.circuit_name, # 代表のサーキット名
                    'notes': s.notes or ""
                }
            daily_slots[s.date]['titles'].add(s.title)
            # 備考は最初のものを優先採用（または結合してもよいが長くなるため）
            if not daily_slots[s.date]['notes'] and s.notes:
                daily_slots[s.date]['notes'] = s.notes

        upcoming_schedules = []
        
        # 集計結果から表示データを作成
        for d_date, d_data in sorted(daily_slots.items()):
            # 1. 桶川のコース判定 (ロング/ミドル/ショート)
            course_label = ""
            if "桶川" in d_data['circuit_name']:
                if "ロング" in d_data['circuit_name']:
                    course_label = "ロング"
                elif "ミドル" in d_data['circuit_name']:
                    course_label = "ミドル"
                elif "ショート" in d_data['circuit_name']:
                    course_label = "ショート"
            
            # 2. 走行枠の内訳判定 (大型/ミニ)
            titles = d_data['titles']
            has_large = any("大型" in t for t in titles)
            has_mini = any("ミニ" in t for t in titles)
            
            slot_detail_label = ""
            if has_large and has_mini:
                slot_detail_label = "(大型・ミニ)"
            elif has_large:
                slot_detail_label = "(大型)"
            elif has_mini:
                slot_detail_label = "(ミニ)"
            
            # コース名と内訳を結合 (例: "ロング(大型・ミニ)")
            display_label = f"{course_label}{slot_detail_label}" if course_label else slot_detail_label

            # 3. 入門枠の有無判定
            has_beginner = "入門" in d_data['notes']

            upcoming_schedules.append({
                'date': d_date,
                'course_label': display_label, # 結合したラベル
                'has_beginner': has_beginner,
                'circuit_full_name': d_data['circuit_name']
            })
        # ▲▲▲ 修正ここまで ▲▲▲

        # 天気予報APIエンドポイント
        weather_api_url = None
        if metadata.get('lat') and metadata.get('lng'):
            weather_api_url = url_for('circuit_dashboard.get_circuit_weather', circuit_name=circuit_name)

        circuit_data.append({
            'name': circuit_name,
            'best_session': best_session,
            'latest_session': latest_session_obj,
            'latest_vehicle_id': latest_vehicle_id,
            'chart_data': chart_data,
            'leaderboard': leaderboard_info,
            'vehicle_breakdown': vehicle_data,
            'target_lap_seconds': target_lap_seconds if target_lap_seconds else None,
            'form': form,
            'metadata': metadata,
            'upcoming_schedules': upcoming_schedules,
            'weather_endpoint': weather_api_url
        })
        
    # 3. 総合サマリー情報を計算
    all_sessions_list = base_query.all()
    total_sessions = len(all_sessions_list)
    total_laps = sum(len(s.lap_times) for a, s in all_sessions_list if s.lap_times)
    
    summary_stats = {
        'total_circuits': len(circuit_data),
        'total_sessions': total_sessions,
        'total_laps': total_laps
    }

    # サーキット名でソートしてテンプレートに渡す
    circuit_data.sort(key=lambda x: x['name'])
    
    return render_template(
        'circuit_dashboard/index.html',
        summary_stats=summary_stats,
        circuit_data=circuit_data,
        format_seconds_to_time=format_seconds_to_time
    )

@circuit_dashboard_bp.route('/weather/<path:circuit_name>')
@login_required
def get_circuit_weather(circuit_name):
    """Open-Meteo APIから天気予報を取得してHTMLフラグメントを返す"""
    metadata = CIRCUIT_METADATA.get(circuit_name)
    
    if not metadata or 'lat' not in metadata or 'lng' not in metadata:
        return '<div class="text-muted small">位置情報未定義</div>'

    try:
        # Open-Meteo API (無料・認証不要)
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": metadata['lat'],
            "longitude": metadata['lng'],
            "daily": "weather_code,temperature_2m_max,precipitation_probability_max",
            "timezone": "Asia/Tokyo",
            "forecast_days": 7
        }
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        # WMO天気コードの簡易変換マップ
        wmo_codes = {
            0: ('快晴', 'fa-sun', 'text-warning'),
            1: ('晴れ', 'fa-sun', 'text-warning'),
            2: ('曇り時々晴れ', 'fa-cloud-sun', 'text-warning'),
            3: ('曇り', 'fa-cloud', 'text-secondary'),
            45: ('霧', 'fa-smog', 'text-secondary'),
            48: ('霧', 'fa-smog', 'text-secondary'),
            51: ('小雨', 'fa-cloud-rain', 'text-info'),
            53: ('雨', 'fa-cloud-rain', 'text-info'),
            55: ('雨', 'fa-cloud-showers-heavy', 'text-primary'),
            61: ('雨', 'fa-umbrella', 'text-primary'),
            63: ('雨', 'fa-umbrella', 'text-primary'),
            65: ('大雨', 'fa-umbrella', 'text-primary'),
            80: ('にわか雨', 'fa-cloud-sun-rain', 'text-info'),
            81: ('にわか雨', 'fa-cloud-sun-rain', 'text-info'),
            82: ('激しい雨', 'fa-cloud-showers-heavy', 'text-primary'),
        }

        daily = data.get('daily', {})
        forecasts = []
        
        dates = daily.get('time', [])
        codes = daily.get('weather_code', [])
        temps = daily.get('temperature_2m_max', [])
        probs = daily.get('precipitation_probability_max', [])

        # 直近5日分を表示
        for i in range(min(5, len(dates))):
            code = codes[i]
            weather_info = wmo_codes.get(code, ('不明', 'fa-cloud', 'text-muted'))
            
            dt = datetime.strptime(dates[i], '%Y-%m-%d')
            is_weekend = dt.weekday() >= 5
            
            forecasts.append({
                'date': dt.strftime('%m/%d') + f" ({['月','火','水','木','金','土','日'][dt.weekday()]})",
                'is_weekend': is_weekend,
                'label': weather_info[0],
                'icon': weather_info[1],
                'color_class': weather_info[2],
                'temp_max': temps[i],
                'precip_prob': probs[i]
            })

        return render_template('circuit_dashboard/_weather_widget.html', forecasts=forecasts)

    except Exception as e:
        current_app.logger.error(f"Weather API Error for {circuit_name}: {e}")
        return '<div class="text-muted small"><i class="fas fa-exclamation-triangle"></i> 天気取得失敗</div>'

@circuit_dashboard_bp.route('/set-target/<path:circuit_name>', methods=['POST'])
@login_required
def set_target_lap_time(circuit_name):
    """目標ラップタイムを設定・更新する"""
    form = TargetLapTimeForm()
    if form.validate_on_submit():
        target_seconds = parse_time_to_seconds(form.target_time.data)
        if target_seconds is None:
            flash('無効なタイム形式です。', 'danger')
            return redirect(url_for('.index'))

        target_entry = UserCircuitTarget.query.filter_by(
            user_id=current_user.id,
            circuit_name=circuit_name
        ).first()

        if target_entry:
            # 既存のエントリを更新
            target_entry.target_lap_seconds = target_seconds
            flash(f'「{circuit_name}」の目標タイムを更新しました。', 'success')
        else:
            # 新しいエントリを作成
            new_target = UserCircuitTarget(
                user_id=current_user.id,
                circuit_name=circuit_name,
                target_lap_seconds=target_seconds
            )
            db.session.add(new_target)
            flash(f'「{circuit_name}」の目標タイムを新規設定しました。', 'success')
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error setting target lap time for user {current_user.id} at {circuit_name}: {e}")
            flash('目標タイムの保存中にエラーが発生しました。', 'danger')

    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{form[field].label.text}: {error}', 'danger')

    return redirect(url_for('.index'))