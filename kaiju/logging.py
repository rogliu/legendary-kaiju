import structlog
from structlog.processors import StackInfoRenderer, TimeStamper, JSONRenderer, add_log_level

_configured = False


def configure_logging() -> None:
    """Configure structlog once per process."""
    global _configured
    if _configured:
        return
    structlog.configure(
        processors=[
            add_log_level,
            StackInfoRenderer(),
            structlog.processors.format_exc_info,
            TimeStamper(fmt="iso"),
            JSONRenderer(),
        ]
    )
    _configured = True


def get_logger(name: str):
    configure_logging()
    return structlog.get_logger(name)
