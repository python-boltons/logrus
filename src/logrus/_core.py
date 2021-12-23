"""Contains the functions/classes that are exposed by logrus' API.

Examples:
    The logger can be initialized before logging is configured:

    >>> logger = Logger("test")

    But should be configured before logging any messages. The call to
    ``init_logging`` below configures our application to log all INFO messages
    (or higher) to stderr using colorful output and all DEBUG messages (or
    higher) to the "test.log" file in JSON:

    >>> init_logging(
    ...     logs=[
    ...         Log(file="stderr", format="color", level="INFO"),
    ...         Log(file="test.log", format="json", level="DEBUG"),
    ...     ]
    ... )

    Note that we can use both string format arguments and keyword arguments:

    >>> logger.info("This logger is %s!", "awesome", reasons_not_to_use=None)

    This logger can also be bound for context-specific logging:

    >>> log = logger.bind(x=1, y=2)
    >>> log.info("This log record will contain x, y, and z.", z=3)

    As a best practice, when a function contains log messages, you should bind
    a logger to the current function's arguments at the start of the function.
    We have written a special logger method just for this purpose:

    >>> log = logger.bind_fargs(arg1="a", arg2="b", arg3="c")
    >>> log.trace("This is TRACE level message!")

    For less typing and to prevent duplicating the function's argument names,
    you can also pass in a dictionary as the first argument to the `bind_fargs`
    method:

    >>> log = logger.bind_fargs(locals())
"""

from dataclasses import dataclass
from inspect import getframeinfo, getmodule
import logging
import logging.config
from os import getpid
from pathlib import Path
from threading import current_thread
from typing import (
    Any,
    Dict,
    Final,
    Iterable,
    List,
    Literal,
    Mapping,
    Optional,
    Tuple,
    Union,
    cast,
)

from metaman import scriptname
import structlog
from structlog._frames import _find_first_app_frame_and_name
from structlog.processors import TimeStamper
from structlog.types import EventDict, Processor


LogFormat = Literal["json", "color", "nocolor"]
LogLevel = Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_ProcReturnType = Union[Mapping[str, Any], str, bytes, Tuple[Any, ...]]
_TRACE_LEVEL: Final = 5
_MEDIUM_FMT: Final = "%H:%M:%S.%f"

# These restricted keys will be bound to the logger automatically and should
# thus never be passed in to `Logger.bind()`.
_RESTRICTED_KEYS = {
    "event",  # log message
    "fargs",  # function arguments
    "function",  # function name
    "lineno",  # line number
    "module",  # module name
    "name",  # logger name
    "pid",  # process ID
    "thread",  # thread name
}

# This dictionary will be populated with the latest arguments used to call this
# module's init_logging() function.
_LOGGING_CONFIGURATION: Dict[str, Any] = {}


@dataclass(frozen=True)
class Log:
    """Log specification for a file or stream.

    Args:
        file: The file to add log messages to (special values: `stderr`,
          `stdout`).
        format: The logging format (e.g. color or json).
        level: The logging level. If this is not set, a reasonable default
          level is used depending on whether we are logging to a file or the
          console (e.g. stderr).
    """

    file: str
    format: LogFormat = "json"
    level: Optional[LogLevel] = None


_DEFAULT_CONSOLE_LOG = Log(file="stderr", format="color")


class BetterBoundLogger(structlog.stdlib.BoundLogger):
    """A better version of structlog's standard BoundLogger.

    Used to add additonal methods to the default BoundLogger.
    """

    # pylint: disable=useless-super-delegation

    def bind(self, **new_values: Any) -> "BetterBoundLogger":
        """Return a new logger with *new_values* added to the existing ones."""
        logger = Logger().bind_fargs(locals())

        for key in list(new_values.keys()):
            if key in _RESTRICTED_KEYS:
                logger.warning("Restricted key cannot be bound.", bad_key=key)
                del new_values[key]

        return super().bind(**new_values)  # type: ignore[return-value]

    def bind_fargs(
        self, fargs_map: Mapping[str, Any] = None, **kwargs: Any
    ) -> "BetterBoundLogger":
        """Helper function for binding function arguments to logger.

        These arguments are passed in as a mapping and then jsonified into a
        string.

        Args:
            fargs_map: A mapping of function arguments. We typically pass in
              `locals()` for this argument at the start of a function that
              contains log messages.
            kwargs: Additional function arguments can be passed in as keyword
              arguments.
        """
        if fargs_map is None:
            fargs = {}
        else:
            fargs = dict(fargs_map.items())

        fargs.update(kwargs)
        return super().bind(fargs=fargs)  # type: ignore[return-value]

    def new(self, **new_values: Any) -> "BetterBoundLogger":
        """We override this function's type signature _only_."""
        return super().new(**new_values)  # type: ignore[return-value]

    def trace(  # pylint: disable=keyword-arg-before-vararg
        self,
        event: Union[str, Dict[str, Any]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Log a new TRACE level message."""
        self.log(
            _TRACE_LEVEL,
            event,  # type: ignore[arg-type]
            *args,
            **kwargs,
        )

    def try_unbind(self, *keys: str) -> "BetterBoundLogger":
        """We override this function's type signature _only_."""
        return super().try_unbind(*keys)  # type: ignore[return-value]

    def unbind(self, *keys: str) -> "BetterBoundLogger":
        """We override this function's type signature _only_."""
        return super().unbind(*keys)  # type: ignore[return-value]


def Logger(name: str = None, **kwargs: Any) -> BetterBoundLogger:
    """Returns a structured logger.

    This logger is capable of handling positional format arguments as well as
    keyword arguments and can be bound for context-specific logging.

    Args:
        name: The name of the logger.
        kwargs: These parameters will be bound to the returned logger.

    Returns:
        A structlog logger with a few extra custom methods (e.g.
        `logger.trace()` and `logger.bind_fargs()`). See structlog's
        documentation for more information:

        https://www.structlog.org/en/stable/loggers.html

    Warning:
        This logger should only be used for applications, NOT libraries.
    """
    if name is None:
        name = scriptname(up=1)

    # If logging is not configured yet...
    if not _LOGGING_CONFIGURATION or not structlog.is_configured():
        # WARNING: This line makes it particularly important that this function
        # only ever be called from applications, NOT libraries.
        init_logging()

    result = structlog.stdlib.get_logger(name)
    result = cast(BetterBoundLogger, result)
    result = result.bind(**kwargs)

    return result


def init_logging(
    *,
    logs: Iterable[Log] = (_DEFAULT_CONSOLE_LOG,),
    verbose: int = 0,
) -> None:
    """Configure standard logging (for libraries) and structlog (for apps).

    This function can be called multiple times but will do nothing if called
    with the same arguments and structlog is still configured (this latter
    check is mostly just needed for testing).

    Args:
        logs: This list of Log objects determines which logging handlers we
          configure and enable, what logging level we use for each handler, and
          what log message format we use for each handler.
        verbose: A non-negative integer. If greater than zero, this option
          affects the default logging level used when a `Log` object in
          ``logs`` does not have its `level` attribute set and causes
          additional values (e.g. PID, thread name) to be added to each log
          record. More precisely, the following rules apply to the ``verbose``
          argument:

          if verbose >= 1...
            - The default log level is set to DEBUG instead of INFO.
            - We show microseconds in each log record's timestamp instead of
              milliseconds.
            - The current PID and thread name are added to each log record.

          if verbose >= 2...
            - The line number, function name, module name, and function
              parameters [if the logger bound them by calling
              `logger.bind_fargs()`] are added to each log record.

          if verbose >= 3...
            - The default log level is set to TRACE instead of INFO.

    Note:
        If no 'stderr' or 'stdout' Log is found in ``logs``, we add a default
        'stderr' Log object to the list.
    """
    assert verbose >= 0

    func_args = locals()
    if _LOGGING_CONFIGURATION == func_args and structlog.is_configured():
        return

    _LOGGING_CONFIGURATION.update(func_args)
    structlog.reset_defaults()

    logs = _set_log_defaults(logs, verbose)

    shared_processors: List[Processor] = [structlog.stdlib.add_log_level]
    verbose_processors: List[Processor] = [
        _add_pid_processor,
        _add_thread_processor,
    ]
    iso_utc_timestamper = TimeStamper(fmt="iso", utc=True)
    very_verbose_processors: List[Processor] = [
        iso_utc_timestamper,
        _add_caller_info_processor,
    ]

    # setup list of JSON processors
    json_processors = list(shared_processors)
    json_processors += (  # json logs are always verbose
        verbose_processors + very_verbose_processors
    )

    # setup list of console (e.g. 'stderr' or 'stdout') processors
    console_processors: List[Processor] = list(shared_processors)
    if verbose >= 2:
        console_processors += verbose_processors + very_verbose_processors
    else:
        # We don't want the 'fargs' key to show up unless we want very verbose
        # output.
        console_processors += [_remove_fargs_processor]

        if verbose == 1:
            timestamper = TimeStamper(fmt=_MEDIUM_FMT, utc=False)
            console_processors += verbose_processors + [timestamper]
        else:
            assert verbose == 0
            console_processors += [_short_timestamper]

    # HACK: The add_logger_name processor cannot be passed to
    # _chain_processors() for some reason since this results in the 'logger'
    # argument being passed into that processor as 'None'.
    #
    # Note that the foreign_pre_chain processors are NOT automatically included
    # in the list of structlog processors (i.e. they are only used for standard
    # logging loggers), so we must explicitly include these in our list of
    # structlog-specific processors.
    foreign_pre_chain = [structlog.stdlib.add_logger_name]

    # colorize custom TRACE level
    level_styles = structlog.dev.ConsoleRenderer.get_default_level_styles()
    level_styles["trace"] = level_styles["debug"]
    color_console_renderer = structlog.dev.ConsoleRenderer(
        colors=True, level_styles=level_styles
    )

    config: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": _chain_processors(
                    structlog.processors.JSONRenderer(sort_keys=True),
                    json_processors,
                ),
                "foreign_pre_chain": foreign_pre_chain,
            },
            "color": {  # requires 'colorama'
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": _chain_processors(
                    color_console_renderer,
                    console_processors,
                ),
                "foreign_pre_chain": foreign_pre_chain,
                "keep_exc_info": True,
                "keep_stack_info": True,
            },
            "nocolor": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": _chain_processors(
                    structlog.dev.ConsoleRenderer(colors=False),
                    console_processors,
                ),
                "foreign_pre_chain": foreign_pre_chain,
                "keep_exc_info": True,
                "keep_stack_info": True,
            },
        },
        "handlers": {},
        "loggers": {
            "": {
                "handlers": [],
                "level": "TRACE",
                "propagate": True,
            },
        },
    }

    # HACK: The following lines are required to setup a custom TRACE logging
    # level with structlog.
    #
    # References
    # ----------
    # https://github.com/hynek/structlog/issues/47
    # https://stackoverflow.com/questions/54505487/custom-log-level-not-working-with-structlog/56467981#56467981
    setattr(structlog.stdlib, "TRACE", _TRACE_LEVEL)
    structlog.stdlib._NAME_TO_LEVEL["trace"] = _TRACE_LEVEL
    structlog.stdlib._LEVEL_TO_NAME[_TRACE_LEVEL] = "trace"
    logging.addLevelName(_TRACE_LEVEL, "TRACE")
    setattr(logging.Logger, "trace", BetterBoundLogger.trace)

    # configure structlog
    structlog_processors: List[Processor] = list(foreign_pre_chain)
    structlog_processors += [
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]
    structlog.configure(
        processors=structlog_processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=BetterBoundLogger,
        cache_logger_on_first_use=True,
    )

    # actual logfiles (i.e. not 'stdout' or 'stderr')
    real_logfiles = []

    # For each Log object...
    for log in logs:
        # The `Log.level` attribute should have been set by the
        # _set_log_defaults() function.
        assert log.level is not None

        # If this Log object refers to a console handler...
        if str(log.file).lower() in ["stderr", "stdout"]:
            config["handlers"][log.file] = {
                "level": log.level,
                "class": "logging.StreamHandler",
                "formatter": log.format,
                "stream": f"ext://sys.{log.file}",
            }
            config["loggers"][""]["handlers"].append(log.file)
        # Otherwise, this Log object refers to a file handler...
        else:
            real_logfiles.append(log.file)
            config["handlers"][log.file] = {
                "level": log.level,
                "class": "logging.handlers.WatchedFileHandler",
                "filename": str(log.file),
                "formatter": log.format,
            }
            config["loggers"][""]["handlers"].append(str(log.file))

    logging.config.dictConfig(config)

    if real_logfiles:
        # WARNING: We have to be careful where we call Logger() inside this
        # function since we could trigger infinite recursion.
        logger = Logger().bind_fargs(func_args)
        logger.info("Logging to files.", logfiles=real_logfiles)


def get_default_logfile(stem: str) -> Path:
    """Returns full path to logfile using default directory locations.

    Args:
        stem: The logfile's final path component, without its suffix.
    """
    log_base = f"{stem}.log"
    var_tmp = Path("/var/tmp")
    if var_tmp.exists():
        return var_tmp / log_base
    else:
        return Path(log_base)


def _set_log_defaults(logs: Iterable[Log], verbose: int = 0) -> List[Log]:
    """Sets default logging levels and possibly adds an 'stderr' Log.

    Returns:
        A list of Log objects equivalent to the ``logs`` argument with the
        following exceptions:
            * The `Log.level` attribute has been set for each Log object.
            * At least one 'stdout' or 'stderr' Log object is contained in the
              final list of logs (we add a default 'stderr' Log to force this to
              be true if necessary).
    """
    result = []

    default_console_level: LogLevel
    default_file_level: LogLevel
    if verbose >= 3:
        default_console_level = default_file_level = "TRACE"
    elif verbose >= 1:
        default_console_level = default_file_level = "DEBUG"
    else:
        assert verbose == 0
        default_console_level = "INFO"
        default_file_level = "DEBUG"

    for log in logs:
        # If the log level is already set for this Log object...
        if log.level is not None:
            result.append(log)
            continue

        file = log.file
        format_ = log.format

        # Otherwise, we choose a default log level based on whether this Log
        # object corresponds to a console handler or a file handler...
        level: LogLevel
        if file in ["stdout", "stderr"]:
            level = default_console_level
        else:
            level = default_file_level

        result.append(Log(file=file, format=format_, level=level))

    # If no 'stderr' or 'stdout' Log has been set explicitly...
    if not any(log.file in ["stderr", "stdout"] for log in logs):
        # Then we add a default 'stderr' Log to our final list of Log objects.
        result.append(
            Log(
                file=_DEFAULT_CONSOLE_LOG.file,
                format=_DEFAULT_CONSOLE_LOG.format,
                level=default_console_level,
            )
        )

    return result


def _chain_processors(
    final_processor: Processor, pre_processors: Iterable[Processor]
) -> Processor:
    """Chain ``pre_processors`` with ``final_processor``.

    This function is a hack used to allow structlog loggers (e.g.
    `logrus.Logger(__name__)`) to conditionally include processors based on
    the handler (e.g. stream vs file).
    """

    def processor(
        logger: Optional[logging.Logger],
        method_name: str,
        event_dict: EventDict,
    ) -> _ProcReturnType:
        for proc in pre_processors:
            event_dict = proc(  # type: ignore[assignment]
                logger, method_name, event_dict
            )
        return final_processor(logger, method_name, event_dict)

    return processor


def _short_timestamper(
    logger: Optional[logging.Logger],
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """A TimeStamper-like function that uses our shortest timestamp format."""
    ts_key: Final = "timestamp"  # timestamp key

    timestamper = TimeStamper(fmt=_MEDIUM_FMT, utc=False, key=ts_key)
    event_dict = timestamper(logger, method_name, event_dict)

    # converts microseconds to milliseconds
    event_dict[ts_key] = event_dict[ts_key][:-3]

    return event_dict


def _add_caller_info_processor(
    _logger: Optional[logging.Logger],
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Custom structlog processor that adds call-site info.

    This processor adds the module name, function name, and line number to the
    event dictionary (i.e. `event_dict`).
    """
    additional_ignores = ["logging"]
    if "logger" not in event_dict or event_dict["logger"] != __name__:
        additional_ignores.append(__name__)

    frame, _name = _find_first_app_frame_and_name(
        additional_ignores=additional_ignores
    )

    if not frame:
        return event_dict

    frameinfo = getframeinfo(frame)

    if not frameinfo:
        return event_dict  # type: ignore[unreachable]

    module = getmodule(frame)
    if not module:
        return event_dict

    event_dict["module"] = module.__name__
    event_dict["function"] = frameinfo.function
    event_dict["lineno"] = str(frameinfo.lineno)

    return event_dict


def _remove_fargs_processor(
    _logger: Optional[logging.Logger], _method_name: str, event_dict: EventDict
) -> EventDict:
    """Removes the 'fargs' key from the event dictionary.

    Note:
        This processor is useful for keeping console logging output more
        managable when extra verbosity is not required (e.g. during normal
        program execution).
    """
    if "fargs" in event_dict:
        del event_dict["fargs"]
    return event_dict


def _add_pid_processor(
    _logger: Optional[logging.Logger],
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Adds the current process ID to the event dictionary."""
    event_dict["pid"] = getpid()
    return event_dict


def _add_thread_processor(
    _logger: Optional[logging.Logger],
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Adds the current thread name to the event dictionary."""
    event_dict["thread"] = current_thread().name
    return event_dict
