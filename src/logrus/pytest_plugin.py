"""A pytest plugin for testing the logrus package.

This plugin can be enabled via the `pytest_plugins` conftest.py variable. This
allows us to use this plugin in external packages' tests instead of just for
this package's tests.

Examples:
    The following line should be found in the "tests/conftest.py" file:

    >>> pytest_plugins = ["logrus.pytest_plugin"]
"""

from pytest import fixture
from pytest_mock.plugin import MockerFixture


@fixture
def mock_dynamic_log_fields(mocker: MockerFixture) -> None:
    """Mock dynamic fields that may be contained in log records."""
    mocker.patch("logrus._core.getpid", return_value=12345)

    frameinfo = mocker.MagicMock()
    setattr(frameinfo, "function", "fake_function")
    setattr(frameinfo, "lineno", "123")
    mocker.patch(
        "logrus._core.getframeinfo",
        return_value=frameinfo,
    )

    mod = mocker.MagicMock()
    setattr(mod, "__name__", "fake_module")
    mocker.patch("logrus._core.getmodule", return_value=mod)
