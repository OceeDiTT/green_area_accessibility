import pytest
from helpers import make_cfg, make_scored


@pytest.fixture
def cfg():
    return make_cfg()


@pytest.fixture
def scored(cfg):
    return make_scored(cfg=cfg)
