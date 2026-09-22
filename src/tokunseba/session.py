"""Match each request to a conversation by hashing its message prefix, so only the delta is ever touched."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .protocols.base import sha256_text


@dataclass
class Match:
    session_id: str
    prefix_len: int
    previous_request_id: str
    is_new: bool


@dataclass
class SessionState:
    chain: list[str] = field(default_factory=list)
    last_request_id: str = ""
    breakpoints: list[tuple[str, str]] = field(default_factory=list)
    regions: dict[str, str] = field(default_factory=dict)
    region_text: dict[str, str] = field(default_factory=dict)
    total_input_tokens: int = 0
    delta_chars: int = 0
    last_ts: float = 0.0
    gaps: list[float] = field(default_factory=list)
    turns: int = 0


class SessionIndex:
    def __init__(self, max_chains: int = 500):
        self.max_chains = max_chains
        self.sessions: dict[str, SessionState] = {}
        self._order: list[str] = []

    def match(self, chain: list[str]) -> Match:
        best_id, best_len = "", -1
        for sid, st in self.sessions.items():
            n = len(st.chain)
            if n <= len(chain) and chain[:n] == st.chain and n > best_len:
                best_id, best_len = sid, n
        if best_id:
            return Match(best_id, best_len, self.sessions[best_id].last_request_id, False)
        # a retry or a regeneration: the stored chain extends the new one
        for sid, st in self.sessions.items():
            if chain and len(chain) <= len(st.chain) and st.chain[:len(chain)] == chain:
                return Match(sid, len(chain), st.last_request_id, False)
        seed = chain[0] if chain else str(time.time())
        return Match(sha256_text(seed)[:16], 0, "", True)

    def commit(self, session_id: str, request_id: str, chain: list[str],
               breakpoints: list[tuple[str, str]] | None = None,
               regions: dict[str, str] | None = None,
               region_text: dict[str, str] | None = None,
               total_input_tokens: int = 0, delta_chars: int = 0) -> None:
        st = self.sessions.get(session_id)
        now = time.time()
        if st is None:
            st = SessionState()
            self.sessions[session_id] = st
            self._order.append(session_id)
            while len(self._order) > self.max_chains:
                self.sessions.pop(self._order.pop(0), None)
        else:
            if st.last_ts:
                st.gaps.append(now - st.last_ts)
                st.gaps = st.gaps[-50:]
        st.chain = list(chain)
        st.last_request_id = request_id
        if breakpoints is not None:
            st.breakpoints = breakpoints
        if regions is not None:
            st.regions = regions
        if region_text is not None:
            st.region_text = region_text
        st.total_input_tokens = total_input_tokens
        st.delta_chars = delta_chars
        st.last_ts = now
        st.turns += 1

    def get(self, session_id: str) -> SessionState | None:
        return self.sessions.get(session_id)
