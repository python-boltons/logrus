"""This file contains shared fixtures and pytest hooks.

https://docs.pytest.org/en/6.2.x/fixture.html#conftest-py-sharing-fixtures-across-multiple-files
"""

from typing import Iterator

from freezegun import freeze_time
from pytest import fixture


pytest_plugins = ["logrus.pytest_plugin"]


@fixture(autouse=True, scope="session")
def frozen_time() -> Iterator[None]:
    """Freeze time until our tests are done running."""
    with freeze_time("2021-09-06T15:45:03.585481Z"):
        yield
