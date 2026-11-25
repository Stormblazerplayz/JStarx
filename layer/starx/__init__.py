"""StarShell: the JStarx desktop shell and app runtime."""
import json
import os

_here = os.path.dirname(os.path.abspath(__file__))


def layer_version():
    try:
        with open(os.path.join(_here, "..", "layer.json")) as f:
            return json.load(f).get("version", "0.0.0")
    except (OSError, ValueError):
        return "0.0.0"


__version__ = layer_version()
