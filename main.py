from __future__ import annotations

import json
import math
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent
COLORS = {"coral": "C", "sun": "S", "aqua": "A", "lime": "L"}
COLOR_NAMES = {symbol: name for name, symbol in COLORS.items()}
LEVELS = ((12, 78, "CSA"), (15, 68, "CSA"), (18, 58, "CSAL"), (21, 48, "CSAL"))
ROUTE_DISTANCE = 1500
MARBLE_SPACING = 28


class Marble:
    def __init__(self, color: str) -> None:
        self.color = color
        self.previous: Marble | None = None
        self.next: Marble | None = None


class MarbleChain:
    def __init__(self, pattern: str = "") -> None:
        self.first: Marble | None = None
        self.last: Marble | None = None
        self.size = 0
        for color in pattern:
            self._append_end(color)

    @classmethod
    def randomized(cls, size: int, colors: str) -> MarbleChain:
        chain = cls()
        while chain.size < size:
            available_colors = colors
            if chain.last is not None and chain.last.previous is not None:
                if chain.last.color == chain.last.previous.color:
                    available_colors = "".join(color for color in colors if color != chain.last.color)
            chain._append_end(random.choice(available_colors))
        return chain

    def _append_end(self, color: str) -> Marble:
        marble = Marble(color)
        marble.previous = self.last
        if self.last is None:
            self.first = marble
        else:
            self.last.next = marble
        self.last = marble
        self.size += 1
        return marble

    def at(self, position: int) -> Marble:
        if position < 0 or position >= self.size:
            raise IndexError("Position is outside the marble chain.")
        if position <= self.size // 2:
            marble = self.first
            for _ in range(position):
                assert marble is not None
                marble = marble.next
        else:
            marble = self.last
            for _ in range(self.size - position - 1):
                assert marble is not None
                marble = marble.previous
        assert marble is not None
        return marble

    def insert(self, position: int, color: str) -> Marble:
        if position < 0 or position > self.size:
            raise IndexError("Insertion point is outside the marble chain.")
        if position == self.size:
            return self._append_end(color)

        following = self.at(position)
        preceding = following.previous
        marble = Marble(color)
        marble.previous = preceding
        marble.next = following
        following.previous = marble
        if preceding is None:
            self.first = marble
        else:
            preceding.next = marble
        self.size += 1
        return marble

    def _remove_range(self, beginning: Marble, ending: Marble, amount: int) -> tuple[Marble | None, Marble | None]:
        preceding = beginning.previous
        following = ending.next
        if preceding is None:
            self.first = following
        else:
            preceding.next = following
        if following is None:
            self.last = preceding
        else:
            following.previous = preceding
        beginning.previous = None
        ending.next = None
        self.size -= amount
        return preceding, following

    def clear_matches(self, inserted: Marble) -> tuple[int, int]:
        beginning = inserted
        ending = inserted
        amount = 1
        while beginning.previous is not None and beginning.previous.color == inserted.color:
            beginning = beginning.previous
            amount += 1
        while ending.next is not None and ending.next.color == inserted.color:
            ending = ending.next
            amount += 1
        if amount < 3:
            return 0, 0

        self._remove_range(beginning, ending, amount)
        return amount, 0

    def encode(self) -> str:
        result = ""
        marble = self.first
        while marble is not None:
            result += marble.color
            marble = marble.next
        return result


class MarbleArcade:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.score = 0
        self.shots = 0
        self.level = 1
        self.unlocked_level = 1
        self.lives = 3
        self.status = "menu"
        self.level_duration = LEVELS[0][1]
        self.active_colors = LEVELS[0][2]
        self.chain = MarbleChain()
        self.current_color = random.choice(self.active_colors)
        self.next_color = random.choice(self.active_colors)
        self.started_at: float | None = None
        self.pullback = 0
        self.event_count = 0
        self.last_event = ""

    def start(self, level: int) -> None:
        if isinstance(level, bool) or not isinstance(level, int):
            raise ValueError("Choose an unlocked level.")
        if level < 1 or level > self.unlocked_level:
            raise ValueError("That level is still locked.")
        self.score = 0
        self.shots = 0
        self.lives = 3
        self.level = level
        self.status = "playing"
        self._start_level()

    def return_to_map(self) -> None:
        self.status = "menu"
        self.started_at = None

    def _start_level(self) -> None:
        chain_size, self.level_duration, self.active_colors = LEVELS[self.level - 1]
        self.chain = MarbleChain.randomized(chain_size, self.active_colors)
        self.current_color = random.choice(self.active_colors)
        self.next_color = random.choice(self.active_colors)
        self.started_at = time.monotonic()
        self.pullback = 0

    def _update_clock(self) -> None:
        if self.status != "playing" or self.started_at is None:
            return
        if time.monotonic() - self.started_at < self.level_duration:
            return
        self.lives -= 1
        self.event_count += 1
        self.last_event = "life_lost"
        if self.lives == 0:
            self.status = "lost"
            self.started_at = None
        else:
            self._start_level()

    def snapshot(self) -> dict[str, Any]:
        self._update_clock()
        elapsed = time.monotonic() - self.started_at if self.started_at is not None else 0
        if self.status == "playing":
            time_left = max(0, math.ceil(self.level_duration - elapsed))
        else:
            time_left = self.level_duration if self.status == "menu" else 0
        return {
            "chain": self.chain.encode(),
            "score": self.score,
            "shots": self.shots,
            "level": self.level,
            "level_count": len(LEVELS),
            "level_duration": self.level_duration,
            "unlocked_level": self.unlocked_level,
            "lives": self.lives,
            "status": self.status,
            "time_left": time_left,
            "progress": min(100, elapsed * 100 / self.level_duration) if self.status == "playing" else 100 if self.status == "lost" else 0,
            "marbles_left": self.chain.size,
            "current_color": COLOR_NAMES[self.current_color],
            "next_color": COLOR_NAMES[self.next_color],
            "active_colors": len(self.active_colors),
            "event_count": self.event_count,
            "last_event": self.last_event,
            "pullback": self.pullback,
        }

    def shoot(self, position: int) -> dict[str, Any]:
        self._update_clock()
        if self.status != "playing":
            raise ValueError("This run has ended. Start a new run to play again.")
        if isinstance(position, bool) or not isinstance(position, int):
            raise ValueError("Choose a valid gap in the chain.")
        if position < 0 or position > self.chain.size:
            raise ValueError("Choose a valid gap in the chain.")

        played_color = self.current_color
        inserted = self.chain.insert(position, played_color)
        removed, cascades = self.chain.clear_matches(inserted)
        self.shots += 1
        self.score += removed * 100 + cascades * 250
        self.pullback += removed * MARBLE_SPACING
        level_cleared = self.chain.size == 0
        self.current_color = self.next_color
        self.next_color = random.choice(self.active_colors)
        if level_cleared:
            self.score += self.level * 500
            if self.level == len(LEVELS):
                self.status = "won"
            else:
                self.unlocked_level = max(self.unlocked_level, self.level + 1)
                self.status = "stage_clear"
        return {
            "removed": removed,
            "cascades": cascades,
            "played_color": COLOR_NAMES[played_color],
            "matched_color": COLOR_NAMES[played_color] if removed else None,
            "level_cleared": level_cleared,
            **self.snapshot(),
        }


GAME = MarbleArcade()


class GameRequestHandler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", status)

    def do_GET(self) -> None:
        if self.path == "/api/state":
            with GAME._lock:
                self._send_json(GAME.snapshot())
            return
        file_name = {"/": "index.html", "/index.html": "index.html", "/style.css": "style.css"}.get(self.path)
        if file_name is None:
            self._send(b"Not found", "text/plain; charset=utf-8", 404)
            return
        content_type = "text/css; charset=utf-8" if file_name.endswith(".css") else "text/html; charset=utf-8"
        self._send((ROOT / file_name).read_bytes(), content_type)

    def do_POST(self) -> None:
        if self.path not in ("/api/shoot", "/api/start", "/api/menu", "/api/reset"):
            self._send_json({"error": "Not found."}, 404)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length < 0 or content_length > 4096:
                raise ValueError("Request is too large.")
            payload = json.loads(self.rfile.read(content_length))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be an object.")
            with GAME._lock:
                if self.path == "/api/start":
                    GAME.start(payload.get("level"))
                elif self.path == "/api/menu":
                    GAME.return_to_map()
                elif self.path == "/api/reset":
                    GAME.start(GAME.level)
                else:
                    self._send_json(GAME.shoot(payload.get("position")))
                    return
                self._send_json(GAME.snapshot())
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, 400)

    def log_message(self, format_string: str, *args: Any) -> None:
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), GameRequestHandler)
    print(f"Marble Arcade is running at http://127.0.0.1:{port}")
    server.serve_forever()