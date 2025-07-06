# motopuppu/utils/datetime_helpers.py
import datetime
from zoneinfo import ZoneInfo

# 日本時間のタイムゾーンを定義
JST = ZoneInfo("Asia/Tokyo")
UTC = datetime.timezone.utc

def format_utc_to_jst_string(utc_dt, format_str='%Y年%m月%d日 %H:%M'):
    """
    タイムゾーン情報を持たない (naive) UTCのdatetimeオブジェクトを、
    JST（日本標準時）の指定された書式の文字列に変換する。
    
    :param utc_dt: タイムゾーン情報のないUTCのdatetimeオブジェクト
    :param format_str: 出力する文字列の書式
    :return: JSTに変換・フォーマットされた文字列。utc_dtがNoneの場合はNoneを返す。
    """
    if not utc_dt or not isinstance(utc_dt, datetime.datetime):
        return None
    
    # datetimeオブジェクトがnaive（タイムゾーン情報なし）の場合、UTCとして扱う
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
        
    # JSTに変換
    jst_dt = utc_dt.astimezone(JST)
    
    return jst_dt.strftime(format_str)