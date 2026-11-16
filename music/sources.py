"""Turning what the user typed into playable tracks.

- YouTube and SoundCloud links (single tracks or playlists) go through yt-dlp.
- Spotify links are resolved to "artist - title" via the Spotify Web API, then
  played from the best YouTube match, because Spotify does not allow streaming.
- Anything else is treated as a YouTube search.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import yt_dlp

log = logging.getLogger(__name__)

MAX_PLAYLIST_TRACKS = 100

SPOTIFY_RE = re.compile(
    r"(?:https?://)?open\.spotify\.com/(?:intl-[a-z]+/)?(track|album|playlist)/([A-Za-z0-9]+)"
)

# Used to look up metadata only (fast, no stream URLs).
_FLAT_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "logger": logging.getLogger("yt_dlp"),
    "extract_flat": "in_playlist",
    "skip_download": True,
    "default_search": "ytsearch",
    "playlistend": MAX_PLAYLIST_TRACKS,
}

# Used right before playback to get a fresh audio stream URL.
_STREAM_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "format": "bestaudio/best",
    "noplaylist": True,
    "skip_download": True,
    "default_search": "ytsearch",
}


class SourceError(Exception):
    """A user-facing problem resolving a query."""


@dataclass
class Track:
    title: str
    # A URL yt-dlp can open, or a "ytsearch1:..." query (used for Spotify tracks).
    source: str
    requester: str
    duration: Optional[int] = None  # seconds
    webpage_url: Optional[str] = None
    stream_url: Optional[str] = field(default=None, repr=False)

    @property
    def duration_str(self) -> str:
        if not self.duration:
            return "?:??"
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    @property
    def display(self) -> str:
        if self.webpage_url:
            return f"[{self.title}]({self.webpage_url}) `{self.duration_str}`"
        return f"**{self.title}** `{self.duration_str}`"


def _is_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


# ---------------------------------------------------------------- yt-dlp ----

def _extract_flat(query: str) -> dict:
    with yt_dlp.YoutubeDL(_FLAT_OPTS) as ydl:
        return ydl.extract_info(query, download=False)


def _entry_url(entry: dict) -> Optional[str]:
    url = entry.get("webpage_url") or entry.get("url")
    if url and not _is_url(url) and entry.get("ie_key") == "Youtube":
        url = f"https://www.youtube.com/watch?v={url}"
    return url


def _resolve_ytdlp(query: str, requester: str) -> list[Track]:
    if not _is_url(query):
        query = f"ytsearch1:{query}"
    try:
        info = _extract_flat(query)
    except yt_dlp.utils.DownloadError as e:
        log.warning("yt-dlp failed for %r: %s", query, e)
        raise SourceError("Couldn't load that link or search. It may be private, region-locked or removed.") from e
    if info is None:
        raise SourceError("Nothing found.")

    entries = info.get("entries")
    if entries is None:  # a single track
        entries = [info]

    tracks = []
    for entry in entries:
        if not entry:
            continue
        url = _entry_url(entry)
        if not url:
            continue
        tracks.append(
            Track(
                title=entry.get("title") or url,
                source=url,
                requester=requester,
                duration=entry.get("duration"),
                webpage_url=url,
            )
        )
        if len(tracks) >= MAX_PLAYLIST_TRACKS:
            break
    if not tracks:
        raise SourceError("Nothing found.")
    return tracks


def _get_stream(track: Track) -> None:
    """Fill in a fresh stream URL (they expire, so do it right before playing)."""
    with yt_dlp.YoutubeDL(_STREAM_OPTS) as ydl:
        info = ydl.extract_info(track.source, download=False)
    if info and "entries" in info:  # a search result
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise SourceError(f"No playable match for {track.title}.")
        info = entries[0]
    if not info or not info.get("url"):
        raise SourceError(f"Couldn't get audio for {track.title}.")
    track.stream_url = info["url"]
    track.duration = track.duration or info.get("duration")
    track.webpage_url = track.webpage_url or info.get("webpage_url")


# --------------------------------------------------------------- Spotify ----

_spotify = None


def _spotify_client():
    global _spotify
    if _spotify is None:
        cid = os.getenv("SPOTIFY_CLIENT_ID")
        secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        if not cid or not secret:
            raise SourceError(
                "Spotify links need SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in the bot's .env file."
            )
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials

        _spotify = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(client_id=cid, client_secret=secret)
        )
    return _spotify


def _spotify_track(t: dict, requester: str) -> Optional[Track]:
    if not t or t.get("type", "track") != "track" or not t.get("name"):
        return None
    artists = ", ".join(a["name"] for a in t.get("artists", []) if a.get("name"))
    title = f"{artists} - {t['name']}" if artists else t["name"]
    duration = t.get("duration_ms")
    return Track(
        title=title,
        source=f"ytsearch1:{title} audio",
        requester=requester,
        duration=duration // 1000 if duration else None,
    )


def _paged(sp, page: dict):
    while page:
        yield from page.get("items", [])
        page = sp.next(page) if page.get("next") else None


def _resolve_spotify(kind: str, spotify_id: str, requester: str) -> list[Track]:
    import spotipy

    sp = _spotify_client()
    try:
        if kind == "track":
            raw = [sp.track(spotify_id)]
        elif kind == "album":
            raw = list(_paged(sp, sp.album_tracks(spotify_id)))
        else:
            raw = []
            for item in _paged(sp, sp.playlist_items(spotify_id, additional_types=("track",))):
                if isinstance(item, dict):
                    raw.append(item.get("track") or item.get("item"))
                if len(raw) >= MAX_PLAYLIST_TRACKS:
                    break
    except spotipy.SpotifyException as e:
        raise SourceError(
            "Spotify wouldn't share that (it may be private, or a Spotify-made playlist the API blocks)."
        ) from e

    tracks = [t for t in (_spotify_track(r, requester) for r in raw[:MAX_PLAYLIST_TRACKS]) if t]
    if not tracks:
        raise SourceError("That Spotify link has no playable tracks.")
    return tracks


# ---------------------------------------------------------------- public ----

async def resolve(query: str, requester: str) -> list[Track]:
    query = query.strip().strip("<>")
    loop = asyncio.get_running_loop()
    m = SPOTIFY_RE.search(query)
    if m:
        return await loop.run_in_executor(None, _resolve_spotify, m.group(1), m.group(2), requester)
    return await loop.run_in_executor(None, _resolve_ytdlp, query, requester)


async def prepare(track: Track) -> None:
    await asyncio.get_running_loop().run_in_executor(None, _get_stream, track)
