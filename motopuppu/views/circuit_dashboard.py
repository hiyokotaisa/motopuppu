# motopuppu/views/circuit_dashboard.py
import re
import decimal
import requests
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, current_app, url_for, request, flash, redirect
from flask_login import login_required, current_user
from sqlalchemy import func, case, or_, desc
from sqlalchemy.orm import aliased, joinedload, defer

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

# 走行枠名から大型/ミニのバイク区分表記(括弧付き含む)を取り除く正規表現
_BIKE_CLASS_PATTERN = re.compile(r'[\(（]\s*(?:大型|ミニ)\s*[\)）]|大型|ミニ')


def _clean_slot_title(title):
    """走行枠名から「(大型)」「(ミニ)」等のバイク区分表記を除去してベース名を返す。"""
    if not title:
        return ""
    cleaned = _BIKE_CLASS_PATTERN.sub('', title)
    return cleaned.strip()


def _course_label_from_name(circuit_name):
    """桶川のサーキット名からコース種別ラベル(ロング/ミドル/ショート)を判定する。"""
    if "桶川" in (circuit_name or ""):
        if "ロング" in circuit_name:
            return "ロング"
        if "ミドル" in circuit_name:
            return "ミドル"
        if "ショート" in circuit_name:
            return "ショート"
    return ""


def _build_sessions_from_slots(schedules):
    """同一コースの走行枠リストを (開始/終了時刻・走行枠名) 単位のセッションへ集約する。

    同一時間帯の大型/ミニは1セッションに集約し、補足(notes)もまとめる。
    Returns: (sessions: list[dict], has_beginner: bool)
    """
    slots = {}
    for s in schedules:
        base_title = _clean_slot_title(s.title)
        slot_key = (s.start_time, s.end_time, base_title)
        if slot_key not in slots:
            slots[slot_key] = {
                'start_time': s.start_time,
                'end_time': s.end_time,
                'title': base_title,
                'bikes': set(),
                'notes_list': [],
                'is_beginner': False,
            }
        slot = slots[slot_key]

        if "大型" in (s.title or ""):
            slot['bikes'].add('大型')
        if "ミニ" in (s.title or ""):
            slot['bikes'].add('ミニ')

        note = (s.notes or "").strip()
        if note and note not in slot['notes_list']:
            slot['notes_list'].append(note)

        haystack = f"{s.title or ''} {s.notes or ''}"
        if "入門" in haystack or "ビギナー" in haystack:
            slot['is_beginner'] = True

    sessions = []
    has_beginner = False
    for slot in slots.values():
        bikes = slot['bikes']
        if bikes == {'大型', 'ミニ'}:
            bikes_label = "大型・ミニ"
        elif bikes == {'大型'}:
            bikes_label = "大型"
        elif bikes == {'ミニ'}:
            bikes_label = "ミニ"
        else:
            bikes_label = ""

        st = slot['start_time']
        et = slot['end_time']
        if st and et:
            time_label = f"{st.strftime('%H:%M')}-{et.strftime('%H:%M')}"
        elif st:
            time_label = st.strftime('%H:%M')
        else:
            time_label = ""

        if slot['is_beginner']:
            has_beginner = True

        sessions.append({
            'time_label': time_label,
            'start_time': st,
            'title': slot['title'],
            'bikes_label': bikes_label,
            'notes': ' / '.join(slot['notes_list']),
            'is_beginner': slot['is_beginner'],
        })

    sessions.sort(key=lambda x: (x['start_time'] is None, x['start_time'] or datetime.min.time()))
    return sessions, has_beginner

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
    # 重いJSON列 (lap_times, gps_tracks) は defer して読み込まない (OOM対策)
    all_sessions_for_graph = base_query.options(
        joinedload(SessionLog.activity),
        defer(SessionLog.lap_times),
        defer(SessionLog.gps_tracks),
    ).order_by(ActivityLog.activity_date.asc()).all()

    today = date.today()
    schedule_horizon = today + timedelta(days=30)

    # ▼▼▼【追加】PBトラッキングデータを全セッションから一括計算 (A-3 + 成長タイムライン + セッションランク) ▼▼▼
    pb_tracking = {}  # circuit_name -> {'count': int, 'last_pb_date': date, 'first_time': Decimal, 'history': list}
    for activity, session in all_sessions_for_graph:
        cn = activity.circuit_name
        if cn not in pb_tracking:
            pb_tracking[cn] = {
                'count': 0,
                'running_min': None,
                'last_pb_date': None,
                'first_time': session.best_lap_seconds,
                'history': []  # 成長タイムライン用PB更新履歴
            }
        if pb_tracking[cn]['running_min'] is None or session.best_lap_seconds < pb_tracking[cn]['running_min']:
            # PB更新時の短縮タイムを計算
            prev_min = pb_tracking[cn]['running_min']
            improvement = float(prev_min - session.best_lap_seconds) if prev_min is not None else 0
            pb_tracking[cn]['running_min'] = session.best_lap_seconds
            pb_tracking[cn]['count'] += 1
            pb_tracking[cn]['last_pb_date'] = activity.activity_date
            pb_tracking[cn]['history'].append({
                'date': activity.activity_date.isoformat(),
                'time': float(session.best_lap_seconds),
                'improvement': round(improvement, 3)
            })
    # ▲▲▲【追加】PBトラッキングここまで ▲▲▲

    for best_session in best_sessions:
        circuit_name = best_session.activity.circuit_name
        
        # 2a. 車両ごとのベストラップと統計を取得
        # NOTE: この個別クエリはfirst_value + partitionの関係で一括化が難しいため維持する
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
            best_session_id_subq.c.best_session_id,
            # ▼▼▼ 追加: セッティングシートIDを取得 ▼▼▼
            SessionLog.setting_sheet_id
        ).join(
            ActivityLog, SessionLog.activity_log_id == ActivityLog.id
        ).join(
            Motorcycle, ActivityLog.motorcycle_id == Motorcycle.id
        ).join(
            best_session_id_subq, Motorcycle.id == best_session_id_subq.c.motorcycle_id
        ).filter(
            ActivityLog.user_id == current_user.id,
            ActivityLog.circuit_name == circuit_name,
            SessionLog.best_lap_seconds.isnot(None),
            # ▼▼▼ 追加: ベストセッションのレコードのみを対象にするためのフィルタ ▼▼▼
            SessionLog.id == best_session_id_subq.c.best_session_id
        ).group_by(
            Motorcycle.id, 
            Motorcycle.name,
            best_session_id_subq.c.best_session_id,
            SessionLog.setting_sheet_id
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
                'best_session_id': row.best_session_id,
                'setting_sheet_id': row.setting_sheet_id
            })
        
        # 2b. ラップタイム推移グラフ（スパークライン）のデータを作成
        chart_data = {
            'labels': [], # 日付
            'data': [],   # ベストラップ
            'ranks': []   # セッションランク
        }
        for activity, session in all_sessions_for_graph:
            if activity.circuit_name == circuit_name:
                chart_data['labels'].append(activity.activity_date.strftime('%Y-%m-%d'))
                lap_sec = float(session.best_lap_seconds)
                chart_data['data'].append(lap_sec)
                # ▼▼▼【追加】セッションランク計算 ▼▼▼
                pb_sec = float(best_session.best_lap_seconds)
                if pb_sec > 0:
                    pct_off = ((lap_sec - pb_sec) / pb_sec) * 100
                else:
                    pct_off = 0
                if lap_sec <= pb_sec:
                    rank = 'S+'
                elif pct_off <= 0.5:
                    rank = 'S'
                elif pct_off <= 1.0:
                    rank = 'A'
                elif pct_off <= 3.0:
                    rank = 'B'
                elif pct_off <= 5.0:
                    rank = 'C'
                else:
                    rank = 'D'
                chart_data['ranks'].append(rank)
                # ▲▲▲【追加】セッションランクここまで ▲▲▲

        # 2c. リーダーボード情報を取得
        leaderboard_info = get_leaderboard_rankings(circuit_name, current_user.id)
        
        # 2d. 最新セッションを取得 (直近の調子判定用)
        # all_sessions_for_graphから該当サーキットの最新を取得（追加クエリを回避）
        latest_session_obj = None
        latest_vehicle_id = None
        for activity, session in reversed(all_sessions_for_graph):
            if activity.circuit_name == circuit_name:
                latest_session_obj = session
                latest_vehicle_id = activity.motorcycle_id
                break
        
        # ログ作成リンク用の車両IDフォールバック
        if not latest_vehicle_id:
            if vehicle_data:
                latest_vehicle_id = vehicle_data[0]['id']
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
        
        # スケジュール取得 (1ヶ月分)
        # 桶川はミニ/大型でコースが分かれるため、施設全体を取得して
        # 自コース(このカードのコース)と他コースに分け、他コースは併記表示する。
        is_okegawa = "桶川" in (circuit_name or "")
        if is_okegawa:
            schedule_filter = TrackSchedule.circuit_name.contains("桶川スポーツランド")
        else:
            schedule_filter = or_(
                TrackSchedule.circuit_name == circuit_name,
                TrackSchedule.circuit_name.contains(circuit_name)
            )

        raw_schedules = TrackSchedule.query.filter(
            TrackSchedule.date >= today,
            TrackSchedule.date <= schedule_horizon,
            schedule_filter
        ).order_by(TrackSchedule.date.asc(), TrackSchedule.start_time.asc()).all()

        target_course_label = _course_label_from_name(circuit_name)

        # 日付 → コース名 → 走行枠リスト に振り分け
        schedules_by_date = {}
        for s in raw_schedules:
            schedules_by_date.setdefault(s.date, {}).setdefault(s.circuit_name, []).append(s)

        upcoming_schedules = []
        for d_date in sorted(schedules_by_date.keys()):
            courses = schedules_by_date[d_date]
            own_sessions = []
            own_has_beginner = False
            other_courses = []

            for course_name, scheds in courses.items():
                sessions, has_beg = _build_sessions_from_slots(scheds)
                clabel = _course_label_from_name(course_name)

                # 自コース判定: 非桶川は常に自コース。桶川はカードのコース種別と
                # 一致するものを自コースとし、それ以外を他コースとして併記する。
                # カードのコース種別が不明な場合は全て自コース扱い。
                is_own = (not is_okegawa) or (not target_course_label) or (clabel == target_course_label)
                if is_own:
                    own_sessions.extend(sessions)
                    if has_beg:
                        own_has_beginner = True
                else:
                    other_courses.append({
                        'course_label': clabel or course_name,
                        'circuit_full_name': course_name,
                        'sessions': sessions,
                    })

            own_sessions.sort(key=lambda x: (x['start_time'] is None, x['start_time'] or datetime.min.time()))
            other_courses.sort(key=lambda x: x['course_label'])

            upcoming_schedules.append({
                'date': d_date,
                'course_label': target_course_label,
                'circuit_full_name': circuit_name,
                'sessions': own_sessions,
                'other_courses': other_courses,
                'has_beginner': own_has_beginner,
            })

        # 天気予報APIエンドポイント
        weather_api_url = None
        if metadata.get('lat') and metadata.get('lng'):
            weather_api_url = url_for('circuit_dashboard.get_circuit_weather', circuit_name=circuit_name)

        # ▼▼▼【追加】PBトラッキングデータを取得 (A-3) ▼▼▼
        circuit_pb = pb_tracking.get(circuit_name, {})
        pb_count = circuit_pb.get('count', 0)
        last_pb_date = circuit_pb.get('last_pb_date')
        first_time = circuit_pb.get('first_time')
        days_since_pb = (today - last_pb_date).days if last_pb_date else None
        is_pb_fresh = days_since_pb is not None and days_since_pb <= 14
        # ▲▲▲【追加】ここまで ▲▲▲

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
            'weather_endpoint': weather_api_url,
            # ▼▼▼【追加】PBトラッキング・プログレス用データ (A-1, A-3, D-1) ▼▼▼
            'pb_count': pb_count,
            'last_pb_date': last_pb_date,
            'days_since_pb': days_since_pb,
            'is_pb_fresh': is_pb_fresh,
            'first_time': first_time,
            # ▲▲▲【追加】ここまで ▲▲▲
            # ▼▼▼【追加】成長タイムライン用PB更新履歴 ▼▼▼
            'pb_history': circuit_pb.get('history', []),
            # ▲▲▲【追加】ここまで ▲▲▲
        })
        
    # 3. 総合サマリー情報を計算 — 全セッションの再ロードを避け、SQL集約で算出 (OOM対策)
    total_sessions = base_query.count()
    total_laps = base_query.with_entities(
        func.coalesce(
            func.sum(func.jsonb_array_length(SessionLog.lap_times)),
            0
        )
    ).filter(SessionLog.lap_times.isnot(None)).scalar() or 0
    total_laps = int(total_laps)

    # ▼▼▼【追加】ストリーク情報 (A-2) ▼▼▼
    first_of_month = today.replace(day=1)
    monthly_circuit_sessions = db.session.query(func.count(func.distinct(ActivityLog.id))).filter(
        ActivityLog.user_id == current_user.id,
        ActivityLog.circuit_name.isnot(None),
        ActivityLog.activity_date >= first_of_month,
        ActivityLog.activity_date <= today
    ).scalar() or 0

    last_circuit_date = db.session.query(func.max(ActivityLog.activity_date)).filter(
        ActivityLog.user_id == current_user.id,
        ActivityLog.circuit_name.isnot(None),
        ActivityLog.activity_date <= today
    ).scalar()
    days_since_last_session = (today - last_circuit_date).days if last_circuit_date else None
    # ▲▲▲【追加】ストリークここまで ▲▲▲
    
    summary_stats = {
        'total_circuits': len(circuit_data),
        'total_sessions': total_sessions,
        'total_laps': total_laps,
        # ▼▼▼【追加】ストリーク情報 (A-2) ▼▼▼
        'monthly_sessions': monthly_circuit_sessions,
        'days_since_last': days_since_last_session,
        # ▲▲▲【追加】ここまで ▲▲▲
    }

    # サーキット名でソートしてテンプレートに渡す
    circuit_data.sort(key=lambda x: x['name'])
    
    # ▼▼▼【追加】ヒートマップカレンダー用データ (過去12ヶ月の走行日) ▼▼▼
    heatmap_query = db.session.query(
        ActivityLog.activity_date,
        func.count(ActivityLog.id)
    ).filter(
        ActivityLog.user_id == current_user.id,
        ActivityLog.circuit_name.isnot(None),
        ActivityLog.activity_date >= today - timedelta(days=365)
    ).group_by(ActivityLog.activity_date).all()
    heatmap_data = {d.isoformat(): c for d, c in heatmap_query}
    # ▲▲▲【追加】ヒートマップここまで ▲▲▲

    template_name = 'beta/circuit_dashboard_beta.html' if current_user.use_beta_ui else 'circuit_dashboard/index.html'
    return render_template(
        template_name,
        summary_stats=summary_stats,
        circuit_data=circuit_data,
        format_seconds_to_time=format_seconds_to_time,
        heatmap_data=heatmap_data
    )

# --- 天気予報用キャッシュ ---
# コース名(緯度経度)ごとに Open-Meteo の取得結果(forecastsリスト)をTTL付きで保持し、
# ページを開くたびに外部APIを叩いてレート制限(429)に達するのを防ぐ。
# gunicornのワーカー毎に独立するが、それでも外部リクエストは大幅に削減できる。
_weather_cache = {}  # circuit_name -> {'forecasts': list|None, 'expires_at': datetime}
_WEATHER_CACHE_TTL_SECONDS = 30 * 60          # 成功時: 30分(Open-Meteoの更新間隔も概ね1時間単位)
_WEATHER_NEGATIVE_CACHE_TTL_SECONDS = 5 * 60  # 失敗時(429含む): 5分のネガティブキャッシュ


def _fetch_weather_forecasts(circuit_name, metadata):
    """Open-Meteo APIから天気予報(forecastsリスト)を取得する。

    コース名単位でTTL付きのインメモリキャッシュを行い、外部APIアクセスを抑制する。
    取得に失敗した場合は短時間のネガティブキャッシュを行い、失敗の連打(429誘発)を防ぐ。
    直近に成功したデータがあれば失敗時もそれを流用する(stale-while-error)。

    :return: forecastsリスト。取得データが一度も得られていない場合は None。
    """
    now = datetime.now()
    cached = _weather_cache.get(circuit_name)
    if cached and now < cached['expires_at']:
        return cached['forecasts']

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

        forecasts = _parse_weather_data(data)
        _weather_cache[circuit_name] = {
            'forecasts': forecasts,
            'expires_at': now + timedelta(seconds=_WEATHER_CACHE_TTL_SECONDS),
        }
        return forecasts

    except Exception as e:
        current_app.logger.error(f"Weather API Error for {circuit_name}: {e}")
        # 失敗時は直近の成功データ(あれば)を流用しつつ、短時間後に再試行する
        stale = cached['forecasts'] if cached else None
        _weather_cache[circuit_name] = {
            'forecasts': stale,
            'expires_at': now + timedelta(seconds=_WEATHER_NEGATIVE_CACHE_TTL_SECONDS),
        }
        return stale


def _parse_weather_data(data):
    """Open-Meteoのレスポンス(JSON)を、テンプレート描画用のforecastsリストに変換する。"""
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
    
    # ▼▼▼【追加】雨天とみなすWMOコード一覧 ▼▼▼
    # 51-57(霧雨), 61-67(雨), 71-77(雪), 80-82(しゅう雨), 85-86(雪しゅう雨), 95-99(雷雨)
    BAD_WEATHER_CODES = [
        51, 53, 55, 56, 57, 
        61, 63, 65, 66, 67, 
        71, 73, 75, 77, 
        80, 81, 82, 
        85, 86, 
        95, 96, 99
    ]

    daily = data.get('daily', {})
    forecasts = []
    
    dates = daily.get('time', [])
    codes = daily.get('weather_code', [])
    temps = daily.get('temperature_2m_max', [])
    probs = daily.get('precipitation_probability_max', [])

    # 直近5日分を表示
    for i in range(min(5, len(dates))):
        code = codes[i]
        max_temp = float(temps[i])
        
        # アイコン情報の取得
        weather_info = wmo_codes.get(code, ('不明', 'fa-cloud', 'text-muted'))
        
        dt = datetime.strptime(dates[i], '%Y-%m-%d')
        is_weekend = dt.weekday() >= 5
        
        # ▼▼▼【追加】走行適性判定ロジック ▼▼▼
        rating_symbol = ''
        rating_class = ''
        
        if code in BAD_WEATHER_CODES:
            rating_symbol = '☓'
            rating_class = 'text-danger fw-bold' # 赤・太字
        elif max_temp < 10.0:
            rating_symbol = '△'
            rating_class = 'text-info fw-bold' # 青・太字 (低温注意)
        else:
            # 雨でなく、10度以上
            if code in [0, 1]: # 快晴・晴れ
                rating_symbol = '◎'
                rating_class = 'text-warning fw-bold' # ゴールド/オレンジっぽく (絶好)
            elif code in [2, 3]: # 曇り
                rating_symbol = '○'
                rating_class = 'text-success fw-bold' # 緑 (良好)
            else:
                # それ以外（霧など）
                rating_symbol = '△' 
                rating_class = 'text-secondary'

        forecasts.append({
            'date': dt.strftime('%m/%d') + f" ({['月','火','水','木','金','土','日'][dt.weekday()]})",
            'is_weekend': is_weekend,
            'label': weather_info[0],
            'icon': weather_info[1],
            'color_class': weather_info[2],
            'temp_max': max_temp,
            'precip_prob': probs[i],
            # 判定結果
            'rating_symbol': rating_symbol,
            'rating_class': rating_class
        })

    return forecasts


@circuit_dashboard_bp.route('/weather/<path:circuit_name>')
@login_required
def get_circuit_weather(circuit_name):
    """Open-Meteo APIから天気予報を取得してHTMLフラグメントを返す(キャッシュ経由)"""
    metadata = CIRCUIT_METADATA.get(circuit_name)

    if not metadata or 'lat' not in metadata or 'lng' not in metadata:
        return '<div class="text-muted small">位置情報未定義</div>'

    forecasts = _fetch_weather_forecasts(circuit_name, metadata)
    if forecasts is None:
        return '<div class="text-muted small"><i class="fas fa-exclamation-triangle"></i> 天気取得失敗</div>'

    return render_template('circuit_dashboard/_weather_widget.html', forecasts=forecasts)

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