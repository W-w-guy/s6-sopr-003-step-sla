# -*- coding: utf-8 -*-
"""pytest 夹具：建库一次、灌数据一次，各用例共享（只读，靠 as_of 刷新切换视图）。

★ 刻意**不在 teardown 里 drop**：verify.py 会用子进程跑 pytest，若子进程退出时把
  物化视图和刷新函数删掉，主进程后续断言就会遇到 "function does not exist"（实测踩到）。
  每个会话开始时 init_schema 自带 DROP ... IF EXISTS 清理，所以不会累积脏对象。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pkg"))

import db  # noqa: E402
import fixtures as F  # noqa: E402


@pytest.fixture(scope="session")
def eng():
    e, how = db.engine()
    db.init_schema(e)          # 内部自带 DROP IF EXISTS，幂等
    db.load_fixtures(e)
    db.refresh(e, F.AS_OF_FULL)   # 参数表必须有行（CROSS JOIN 才不会空）
    return e


@pytest.fixture(scope="session")
def base_rows(eng):
    """as_of=FULL 时的物化视图内容（多数用例的基线）。"""
    db.refresh(eng, F.AS_OF_FULL)
    return db.rows_of_mv(eng)
