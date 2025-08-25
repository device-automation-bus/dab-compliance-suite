# logger.py
from dataclasses import dataclass
from datetime import datetime
import os, sys

# ---------- ANSI ----------
RESET = "\x1b[0m"
BOLD  = "\x1b[1m"
DIM   = "\x1b[2m"
ITAL  = "\x1b[3m"

FG_RED     = "\x1b[31m"
FG_GREEN   = "\x1b[32m"
FG_YELLOW  = "\x1b[33m"
FG_BLUE    = "\x1b[34m"
FG_MAGENTA = "\x1b[35m"
FG_CYAN    = "\x1b[36m"
FG_WHITE   = "\x1b[37m"
FG_GRAY    = "\x1b[90m"  # light gray
FG_BWHITE  = "\x1b[97m"  # bright white

def _now_ms() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False

@dataclass
class RunLogger:
    """
    - [INFO]/[OK]/[WAIT] only when verbose=True (dim, italic, light gray, slightly brighter)
    - [WARN]/[ERROR]/[RESULT]/[FATAL]/[PROMPT] always (bold/bright)
    - Brighter light-gray timestamp with ms on every line
    - Skips blank lines so you won’t see: “[INFO]  ”
    """
    verbose: bool = False
    enable_color: bool = True

    # ---------- styling ----------
    def _style_ts(self, ts: str) -> str:
        if not self.enable_color or not _supports_color():
            return ts
        # brighter light gray: bright white + dim
        return f"{DIM}{FG_BWHITE}{ts}{RESET}"

    def _style_msg(self, level: str, msg: str, always: bool) -> str:
        if not self.enable_color or not _supports_color():
            return msg
        if not always:
            # verbose-only lines: “smaller” but a bit brighter 
            return f"{DIM}{ITAL}{FG_BWHITE}  · {msg}{RESET}"
        # always-on lines: brighter/bolder
        if level == "WARN":
            return f"{BOLD}{FG_YELLOW}{msg}{RESET}"
        if level == "ERROR":
            return f"{BOLD}{FG_RED}{msg}{RESET}"
        if level == "FATAL":
            return f"{BOLD}{FG_RED}{msg}{RESET}"
        if level == "PROMPT":
            return f"{BOLD}{FG_MAGENTA}{msg}{RESET}"
        if level == "RESULT":
            return f"{BOLD}{FG_BWHITE}{msg}{RESET}"
        if level == "OK":
            return f"{BOLD}{FG_GREEN}{msg}{RESET}"
        return f"{BOLD}{msg}{RESET}"

    # ---------- core ----------
    def _emit(self, level: str, msg: str, always: bool = False):
        # skip empty/whitespace-only lines → prevents “[INFO]  ”
        if msg is None or str(msg).strip() == "":
            return
        if always or self.verbose:
            ts = self._style_ts(_now_ms())
            styled = self._style_msg(level, str(msg), always)
            print(f"{ts} [{level}] {styled}")

    # levels
    def info(self, msg: str):   self._emit("INFO", msg, always=False)
    def ok(self, msg: str):     self._emit("OK", msg, always=False)
    def wait(self, msg: str):   self._emit("INFO", msg, always=False)  # keep label for compatibility
    def warn(self, msg: str):   self._emit("WARN", msg, always=True)
    def error(self, msg: str):  self._emit("ERROR", msg, always=True)
    def fatal(self, msg: str):  self._emit("FATAL", msg, always=True)
    def result(self, msg: str): self._emit("RESULT", msg, always=True)
    def prompt(self, msg: str): self._emit("PROMPT", msg, always=True)

    # plain stamped line for persisted logs (no ANSI)
    def stamp(self, line: str) -> str:
        return f"{_now_ms()} {line}"

    # optional helpers
    def test_start(self, name: str, test_id: str, topic: str, device: str, request_body: str, suite: str | None = None):
        bar = "═" * 79
        sep = "─" * 79
        self.result(bar)
        self.result(f"Starting test: {name}")
        self.result(f"Test ID: {test_id}")
        if suite:
            self.result(f"Suite: {suite}")
        self.result(f"Topic: {topic}")
        self.result(f"Device: {device}")
        self.result(f"Request body: {request_body}")
        self.result(sep)

    def test_end(self, outcome: str, duration_ms: int | None = None):
        sep = "─" * 79
        self.result(sep)
        if duration_ms is not None:
            self.result(f"Result: {outcome} · Total wall time: {duration_ms} ms")
        else:
            self.result(f"Result: {outcome}")
        self.result("═" * 79)

    def _fmt_duration(self, ms: int) -> str:
        try:
            ms = int(ms)
        except Exception:
            return f"{ms} ms"
        s, ms = divmod(ms, 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    def suite_footer(self, duration_ms: int, label: str = "Suite Wall Time") -> None:
        self.result("══════════════════════════════════════════════════════════════════════════════")
        self.result(f"{label}: {self._fmt_duration(duration_ms)} ({int(duration_ms)} ms)")

# Shared singleton
LOGGER = RunLogger(verbose=False, enable_color=True)
