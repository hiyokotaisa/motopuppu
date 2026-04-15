# motopuppu/utils/datetime_helpers.py
import datetime
from zoneinfo import ZoneInfo

# 日本時間のタイムゾーンを定義
JST = ZoneInfo("Asia/Tokyo")
UTC = datetime.timezone.utc

def format_utc_to_jst_string(utc_dt, format_str='%Y年%m月%d日 %H:%M'):
    """
    タイムゾーン情報を持たない (naive) UTCのdatetimeオブジェクト、
    またはISO 8601形式の文字列を、JST（日本標準時）の指定された書式の文字列に変換する。
    
    :param utc_dt: datetimeオブジェクト、またはISO 8601形式の日時文字列
    :param format_str: 出力する文字列の書式
    :return: JSTに変換・フォーマットされた文字列。utc_dtがNoneの場合はNoneを返す。
    """
    if not utc_dt:
        return None

    # 文字列の場合はISO 8601としてパースを試みる
    if isinstance(utc_dt, str):
        try:
            # Python 3.11+ の fromisoformat は 'Z' を認識する
            # それ以前のバージョンとの互換性のため、'Z' を '+00:00' に置換
            utc_dt = datetime.datetime.fromisoformat(utc_dt.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return utc_dt  # パースできない場合はそのまま返す
    
    if not isinstance(utc_dt, datetime.datetime):
        return None
    
    # datetimeオブジェクトがnaive（タイムゾーン情報なし）の場合、UTCとして扱う
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
        
    # JSTに変換
    jst_dt = utc_dt.astimezone(JST)
    
    return jst_dt.strftime(format_str)

# ▼▼▼ テンプレートエラー解決のために新しい関数を追記 ▼▼▼
def to_user_localtime(utc_dt):
    """
    UTCのdatetimeオブジェクトをJST（日本標準時）のdatetimeオブジェクトに変換する。
    Jinja2フィルターとして、テンプレート側でstrftimeを使えるようにする。
    
    :param utc_dt: タイムゾーン情報を持つか持たないUTCのdatetimeオブジェクト
    :return: JSTのdatetimeオブジェクト。utc_dtがNoneの場合はNoneを返す。
    """
    if not utc_dt or not isinstance(utc_dt, datetime.datetime):
        return None
    
    # datetimeオブジェクトがnaive（タイムゾーン情報なし）の場合、UTCとして扱う
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
        
    # JSTに変換してdatetimeオブジェクトのまま返す
    return utc_dt.astimezone(JST)
# ▲▲▲ 追記ここまで ▲▲▲