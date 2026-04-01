# motopuppu/utils/search_helpers.py

def escape_like(query_string):
    """
    SQL LIKE 検索で使用する文字列の特殊文字をエスケープする。
    '%' と '_' はLIKEのワイルドカードとして解釈されるため、
    ユーザー入力に含まれる場合はリテラル文字としてエスケープする。
    
    :param query_string: エスケープ対象の文字列
    :return: LIKE パターンとして安全な '%escaped_string%' 形式の文字列
    """
    escaped = query_string.replace('%', '\\%').replace('_', '\\_')
    return f"%{escaped}%"
