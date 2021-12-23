"""Tests for the logrus package."""

import json
import logging
from pathlib import Path
import re
from typing import Any

from _pytest.capture import CaptureFixture
from pytest import fixture, mark
import structlog
from syrupy.assertion import SnapshotAssertion as Snapshot

import logrus


params = mark.parametrize


@fixture(autouse=True)
def mock_fields(mock_dynamic_log_fields: None) -> None:
    """Autouse wrapper around the ``mock_dynamic_log_fields`` fixture."""
    del mock_dynamic_log_fields


@params("verbose", [0, 1, 2, 3])
def test_init_logging__LOGFILE(
    tmp_path: Path,
    snapshot: Snapshot,
    capsys: CaptureFixture,
    verbose: int,
) -> None:
    """Test the init_logging() function when using a logfile."""
    logfile = tmp_path / "test.log"

    logs = [
        logrus.Log(file="stderr", format="nocolor", level="INFO"),
        logrus.Log(file=str(logfile), format="json", level="DEBUG"),
    ]
    logrus.init_logging(logs=logs, verbose=verbose)

    # The logfile(s) are temporary and thus not static, so we need to make sure
    # to remove it from our log messages.
    def mock_logfile_path(contents: str) -> str:
        return re.sub(r"/tmp/[^ ]+\.log", "<REMOVED_FOR_TESTING>", contents)

    _log_stuff()
    captured = capsys.readouterr()

    assert mock_logfile_path(captured.err) == snapshot

    logfile_contents = logfile.read_text()
    logfile_contents = mock_logfile_path(logfile_contents)

    assert logfile_contents == snapshot

    json_log_lines = []
    for line in logfile_contents.split("\n"):
        if not line:
            continue

        record = json.loads(line)
        json_log_lines.append(record)

    assert json_log_lines == snapshot


@params("verbose", [0, 1, 2, 3])
def test_init_logging__NO_LOGFILE(
    snapshot: Snapshot,
    capsys: CaptureFixture,
    verbose: int,
) -> None:
    """Test the init_logging() function when NOT using a logfile."""
    logs = [logrus.Log(file="stderr", format="nocolor")]
    logrus.init_logging(logs=logs, verbose=verbose)
    _log_stuff()

    captured = capsys.readouterr()
    assert captured.err == snapshot


def test_log_before_init(snapshot: Snapshot, capsys: CaptureFixture) -> None:
    """Test that loggers work if used before calling init_logging()."""
    structlog.reset_defaults()
    _log_stuff()
    captured = capsys.readouterr()
    assert captured.err == snapshot


def test_restricted_keys(snapshot: Snapshot, capsys: CaptureFixture) -> None:
    """Test that restricted keys (e.g. 'pid' and 'thread') cannot be bound."""
    logs = [logrus.Log(file="stderr", format="nocolor")]
    logrus.init_logging(logs=logs, verbose=2)

    logger = logrus.Logger("restricted_keys").bind(
        pid=12345, good_key="'Only this key should bind to the logger.'"
    )
    logger.info("Test INFO log message.")

    captured = capsys.readouterr()
    err = captured.err
    err = re.sub(" at 0x[^>]+>", ">", err)

    assert err == snapshot


def _log_stuff(*args: Any, **kwargs: Any) -> None:
    if not args:
        args = ("Hi %s", "there")

    if not kwargs:
        kwargs = {"e": 2, "z": 3}

    fake_func_args = {"a": 1, "b": 2, "c": 3}

    # structlog Logger: pass kwargs into each logging function.
    struct_logger = logrus.Logger("struct_test_1").bind_fargs(fake_func_args)
    struct_logger.trace(*args, **kwargs)
    struct_logger.debug(*args, **kwargs)
    struct_logger.info(*args, **kwargs)
    struct_logger.error(*args, **kwargs)

    # structlog Logger: bind kwargs explicitly using .bind*() methods.
    struct_logger = (
        logrus.Logger("struct_test_2")
        .bind(**kwargs)
        .bind_fargs(fake_func_args)
    )
    struct_logger.trace(*args)
    struct_logger.debug(*args)
    struct_logger.info(*args)
    struct_logger.error(*args)

    # structlog Logger: bind kwargs using logrus.Logger() function.
    struct_logger = logrus.Logger("struct_test_3", **kwargs).bind_fargs(
        fake_func_args
    )
    struct_logger.trace(*args)
    struct_logger.debug(*args)
    struct_logger.info(*args)
    struct_logger.error(*args)

    # Standard Library Logger
    std_logger = logging.getLogger("std_test")
    std_logger.debug(*args)
    std_logger.info(*args)
    std_logger.error(*args)
