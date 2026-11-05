"""Read measured draft diagnostics; does not execute Blender or modify the scene."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=Path('scene_diagnostics.json'))
    parser.add_argument('--role')
    parser.add_argument('--entity')
    parser.add_argument('--cameras', action='store_true')
    parser.add_argument('--support', action='store_true')
    args = parser.parse_args()
    if not args.file.is_file():
        parser.error('Run ./preview.py first; no scene diagnostics are available.')
    data = json.loads(args.file.read_text())
    if args.cameras:
        result = {'cameras': data['cameras'], 'render': data['render']}
    elif args.support:
        result = data['support']
    else:
        result = [e for e in data['entities'] if (not args.role or e['claimed_role'] == args.role)
                  and (not args.entity or e['id'] == args.entity)]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
