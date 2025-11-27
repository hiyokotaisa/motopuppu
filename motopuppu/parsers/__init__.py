# motopuppu/parsers/__init__.py
from .base_parser import BaseLapTimeParser
from .simple_csv_parser import SimpleCsvParser  # SimpleCSVParser -> SimpleCsvParser に修正
from .ziix_parser import ZiixParser             # ZiiXParser -> ZiixParser に修正
from .mylaps_parser import MylapsParser         # MyLapsParser -> MylapsParser に修正
from .drogger_parser import DroggerParser
from .racechrono_parser import RaceChronoParser

PARSERS = {
    'simple_csv': SimpleCsvParser,
    'ziix': ZiixParser,
    'mylaps': MylapsParser,
    'drogger': DroggerParser,
    'racechrono': RaceChronoParser,
}

def get_parser(device_type) -> BaseLapTimeParser:
    """
    指定されたデバイスタイプに対応するパーサークラスのインスタンスを返す
    """
    parser_class = PARSERS.get(device_type)
    if parser_class:
        return parser_class()
    
    # デフォルトまたは該当なしの場合はNoneを返す（呼び出し元で処理）
    return None