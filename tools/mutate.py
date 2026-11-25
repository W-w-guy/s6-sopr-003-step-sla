# -*- coding: utf-8 -*-
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from kitlib import mutate  # noqa: E402

SPEC = json.load(open(os.path.join(ROOT, "spec.json"), encoding="utf-8"))

if __name__ == "__main__":
    sys.exit(mutate.run(ROOT, SPEC["engine_rel"], [tuple(m) for m in SPEC["mutations"]]))
