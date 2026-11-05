"""Reversible table transport for repetitive JSON facts, without dropping fields."""
import json


FORMAT = '3dbench-json-tables-v1'
DESCRIPTION = (
    'Lossless JSON tables: a {$table:[columns,rows]} replaces an array of objects; '
    'each row maps column names to its values in order; {$absent:true} cells omit that key. Decode recursively. '
    '{$object:[[key,value],...]} escapes original objects containing reserved keys. '
    'All facts and evidence paths are preserved; table rows are not summaries.'
)


def encode(value):
    if isinstance(value, dict):
        if any(key in value for key in ('$table', '$object', '$absent')):
            return {'$object': [[key, encode(item)] for key, item in value.items()]}
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) >= 2 and all(isinstance(row, dict) for row in value):
            columns = list(dict.fromkeys(key for row in value for key in row))
            if columns:
                table = {'$table': [columns, [[encode(row[key]) if key in row else {'$absent': True}
                                              for key in columns] for row in value]]}
                plain = [encode(row) for row in value]
                if len(dumps(table)) < len(dumps(plain)):
                    return table
                return plain
        return [encode(item) for item in value]
    return value


def decode(value):
    if isinstance(value, dict):
        if '$table' in value:
            columns, rows = value['$table']
            return [{key: decode(item) for key, item in zip(columns, row, strict=True)
                     if item != {'$absent': True}} for row in rows]
        if '$object' in value:
            return {key: decode(item) for key, item in value['$object']}
        return {key: decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode(item) for item in value]
    return value


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def transport(value):
    encoded = encode(value)
    if decode(encoded) != value:
        raise ValueError('Fact transport round-trip failed')
    envelope = {'encoding': FORMAT, 'decoding': DESCRIPTION, 'value': encoded}
    packed, plain = dumps(envelope), dumps(value)
    return packed if len(packed) < len(plain) else plain
