"""Keep organizer attribution and grading files outside candidate workspaces."""
from pathlib import PurePosixPath
import re

_NOTICE = re.compile(r'(?:credits?|creadits?|licenses?|sources?|provenance|attribution)(?:\.(?:txt|md|json))?', re.I)


def organizer_file(name):
    path = PurePosixPath(str(name).replace('\\', '/'))
    return any(part.casefold() in {'attribution', 'harness', 'solution', 'verifier'}
               for part in path.parts) or bool(_NOTICE.fullmatch(path.name))


def require_public_input(name):
    if organizer_file(name):
        raise ValueError('Organizer metadata cannot be a model-visible input: ' + str(name))
