from pathlib import Path

import pytest

from legalbot.registry import ActInfo
from legalbot.schema import Status

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def sample_act() -> ActInfo:
    return ActInfo(
        act_id="sample",
        name="Sample Penal Act, 2099",
        short="SMP",
        year=2099,
        status=Status.IN_FORCE,
        aliases=("sample penal act", "smp"),
    )


@pytest.fixture(scope="session")
def sample_text() -> str:
    return (FIXTURES / "sample_act.txt").read_text(encoding="utf-8")
