# motopuppu/parsers/__init__.py
from .base_parser import BaseLapTimeParser
from .ziix_parser import ZiixParser
from .mylaps_parser import MylapsParser
# --- ▼▼▼ 変更 ▼▼▼ ---
from .simple_csv_parser import SimpleCsvParser
# --- ▲▲▲ 変更ここまで ▲▲▲ ---
from .drogger_parser import DroggerParser

# マッピングを定義
PARSERS = {
    # --- ▼▼▼ 変更 ▼▼▼ ---
    'simple_csv': SimpleCsvParser,
    # --- ▲▲▲ 変更ここまで ▲▲▲ ---
    'ziix': ZiixParser,
    'mylaps': MylapsParser,
    'drogger': DroggerParser,
}

def get_parser(device_type: str) -> BaseLapTimeParser:
    parser_class = PARSERS.get(device_type)
    if not parser_class:
        raise ValueError(f"サポートされていない機種です: {device_type}")
    return parser_class()