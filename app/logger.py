"""Colorful logging utility using rich"""
from typing import Any

try:
    from rich.console import Console
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    # Fallback if rich is not available
    class MockConsole:
        def print(self, *args, **kwargs):
            print(*args, **kwargs)

    console = MockConsole()
    RICH_AVAILABLE = False


class Logger:
    """Colorful logger using rich"""

    def __init__(self, name: str = "SalesDialer"):
        if RICH_AVAILABLE:
            self.console = Console()
        else:
            self.console = None
        self.name = name

    def _format_message(self, level: str, message: str, *args, **kwargs) -> str:
        """Format log message with timestamp and level"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {self.name} {level}: {message}"

        # Format any additional arguments
        if args:
            formatted_msg += f" {args}"
        if kwargs:
            formatted_msg += f" {kwargs}"

        return formatted_msg

    def _log(self, level: str, message: str, color: str, *args, **kwargs):
        """Internal logging method with rich styling"""
        formatted_msg = self._format_message(level, message, *args, **kwargs)

        if self.console:
            # Use rich for colorful output
            text = Text(formatted_msg, style=color)
            self.console.print(text)
        else:
            # Fallback to plain print
            print(formatted_msg)

    def info(self, message: str, *args, **kwargs):
        """Log info message in blue"""
        self._log("INFO", message, "blue", *args, **kwargs)

    def success(self, message: str, *args, **kwargs):
        """Log success message in green"""
        self._log("SUCCESS", message, "green", *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        """Log warning message in yellow"""
        self._log("WARN", message, "yellow", *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        """Log error message in red"""
        self._log("ERROR", message, "red", *args, **kwargs)

    def debug(self, message: str, *args, **kwargs):
        """Log debug message in cyan"""
        self._log("DEBUG", message, "cyan", *args, **kwargs)

    def agent(self, agent_name: str, message: str, *args, **kwargs):
        """Log agent-specific message in magenta"""
        self._log(f"AGENT:{agent_name}", message, "magenta", *args, **kwargs)

    def call(self, phone: str, message: str, *args, **kwargs):
        """Log call-related message in white"""
        self._log(f"CALL:{phone}", message, "white", *args, **kwargs)


# Global logger instance
logger = Logger("SalesDialer")
