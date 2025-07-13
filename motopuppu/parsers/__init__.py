# motopuppu/parsers/__init__.py
from .base_parser import BaseLapTimeParser
from .ziix_parser import ZiixParser
from .mylaps_parser import MylapsParser

# マッピングを定義
PARSERS = {
    'ziix': ZiixParser,
    'mylaps': MylapsParser,
}

def get_parser(device_type: str) -> BaseLapTimeParser:
    parser_class = PARSERS.get(device_type)
    if not parser_class:
        raise ValueError(f"サポートされていない機種です: {device_type}")
    return parser_class()