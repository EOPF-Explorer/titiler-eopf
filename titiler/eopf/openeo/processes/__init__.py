"""titiler.eopf.openeo processes."""

import importlib
import inspect
import json
from pathlib import Path

from openeo_pg_parser_networkx.process_registry import Process

from titiler.openeo.processes import process_registry

json_path = Path(__file__).parent / "data"
PROCESS_SPECIFICATIONS = {}
for f in (json_path).glob("*.json"):
    spec_json = json.load(open(f))
    process_name = spec_json["id"]
    # Make sure we don't overwrite any builtins (e.g min -> _min)
    # if spec_json["id"] in dir(builtins) or keyword.iskeyword(spec_json["id"]):
    #     process_name = "_" + spec_json["id"]

    PROCESS_SPECIFICATIONS[process_name] = spec_json

PROCESS_IMPLEMENTATIONS = [
    func
    for _, func in inspect.getmembers(
        importlib.import_module("titiler.eopf.openeo.processes.implementations"),
        inspect.isfunction,
    )
]
for func in PROCESS_IMPLEMENTATIONS:
    process_registry[func.__name__] = Process(
        spec=PROCESS_SPECIFICATIONS[func.__name__], implementation=func
    )
