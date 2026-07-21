"""serialize: `to_json`/`from_json` + format versioning (API.md, "to_json
/ from_json").
"""

from designspace.serialize._fromjson import from_json
from designspace.serialize._tojson import to_json
from designspace.serialize._version import FORMAT_VERSION

__all__ = ["FORMAT_VERSION", "from_json", "to_json"]
