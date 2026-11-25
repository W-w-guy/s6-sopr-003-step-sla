# -*- coding: utf-8 -*-
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from kitlib import pii  # noqa: E402

if __name__ == "__main__":
    sys.exit(pii.main(ROOT))
