"""One fixed executable prerequisite for the standalone, synthetic demo."""
import json
from pathlib import Path
import sys


def main():
    try:
        value = json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
    except (OSError, ValueError, IndexError):
        return 2
    valid = (type(value) is dict and set(value) == {'enabled', 'version'}
             and value['enabled'] is True and type(value['version']) is int
             and value['version'] == 2)
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
