# state.py — runtime state (queue, current track, timers)
import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set

START_TIME = time.time()
SUDOERS: Set[int] = set()


@dataclass
class Track:
    title: str = "Unknown"
    duration: int = 0
    thumb: str = ""
    webpage: str = ""          # youtube page / original link
    query: str = ""            # search text (lazy tracks, spotify)
    vid: str = ""
    channel: str = ""
    video: bool = False
    stream_url: str = ""       # direct url ya local file path
    audio_url: str = ""        # sirf video (alag audio stream) ke liye
    headers: Optional[dict] = None
    local: bool = False
    resolved_at: float = 0.0
    requester: str = ""        # HTML mention
    requester_id: int = 0


class ChatState:
    def __init__(self):
        self.queue: List[Track] = []
        self.current: Optional[Track] = None
        self.started: float = 0.0      # wall-clock minus offset (played = now - started)
        self.paused: bool = False
        self.paused_at: float = 0.0
        self.loop: int = 0
        self.autoplay: bool = False
        self.msg = None                # last player message
        self.history: Set[str] = set()
        self.lock = asyncio.Lock()

    @property
    def active(self) -> bool:
        return self.current is not None

    def played(self) -> int:
        if not self.current:
            return 0
        now = self.paused_at if self.paused else time.time()
        p = max(int(now - self.started), 0)
        if self.current.duration:
            p = min(p, self.current.duration)
        return p


_states: Dict[int, ChatState] = {}


def get(chat_id: int) -> ChatState:
    if chat_id not in _states:
        _states[chat_id] = ChatState()
    return _states[chat_id]


def active_chats() -> List[int]:
    return [c for c, s in _states.items() if s.active]
