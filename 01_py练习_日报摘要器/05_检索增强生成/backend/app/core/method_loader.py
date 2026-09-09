import json
from pathlib import Path
from ..core.schemas import RetrievalMethod, RetrievalStep
from typing import Dict


METHODS_DIR = Path(__file__).parent.parent / "methods"


class MethodLoadError(Exception):
    pass


def load_method(method_id: str) -> RetrievalMethod:
    method_file = METHODS_DIR / f"{method_id}.json"
    if not method_file.exists():
        raise MethodLoadError(f"Method file not found: {method_id}")
    
    with open(method_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    steps = [RetrievalStep(**step) for step in data.get("steps", [])]
    
    return RetrievalMethod(
        method_id=data["method_id"],
        description=data.get("description"),
        steps=steps
    )


def get_available_methods() -> Dict[str, str]:
    methods = {}
    if not METHODS_DIR.exists():
        return methods
    
    for method_file in METHODS_DIR.glob("*.json"):
        with open(method_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        methods[data["method_id"]] = data.get("description", "")
    
    return methods