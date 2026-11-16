"""One queue and voice connection per Discord server."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import discord

from .sources import Track, prepare

log = logging.getLogger(__name__)

FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin"
FFMPEG_OPTIONS = "-vn"
IDLE_TIMEOUT = 300  # leave the voice channel after 5 minutes with nothing playing


class GuildPlayer:
    def __init__(self, bot: discord.Client, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue: list[Track] = []
        self.current: Optional[Track] = None
        self.text_channel: Optional[discord.abc.Messageable] = None
        self._next = asyncio.Event()
        self._wakeup = asyncio.Event()
        self._task = bot.loop.create_task(self._run())

    @property
    def voice(self) -> Optional[discord.VoiceClient]:
        return self.guild.voice_client  # type: ignore[return-value]

    def add(self, tracks: list[Track]) -> None:
        self.queue.extend(tracks)
        self._wakeup.set()

    def skip(self) -> bool:
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self.voice.stop()  # triggers the after-callback, which moves to the next track
            return True
        return False

    def stop(self) -> None:
        self.queue.clear()
        self.skip()

    async def destroy(self) -> None:
        self.queue.clear()
        self._task.cancel()
        if self.voice:
            await self.voice.disconnect(force=True)

    async def _say(self, text: str) -> None:
        if self.text_channel:
            try:
                await self.text_channel.send(text, suppress_embeds=True)
            except discord.HTTPException:
                pass

    async def _run(self) -> None:
        while True:
            if not self.queue:
                self._wakeup.clear()
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=IDLE_TIMEOUT)
                except asyncio.TimeoutError:
                    if self.voice and not self.queue:
                        await self._say("Nothing played for a while, so I left the voice channel.")
                        await self.voice.disconnect()
                    continue

            if not self.voice or not self.voice.is_connected():
                self.queue.clear()
                continue

            track = self.queue.pop(0)
            try:
                await prepare(track)
            except Exception as e:  # noqa: BLE001 - one bad track shouldn't stop the queue
                log.warning("Failed to load %s: %s", track.title, e)
                await self._say(f"Skipping **{track.title}**: couldn't load it.")
                continue

            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(
                    track.stream_url, before_options=FFMPEG_BEFORE, options=FFMPEG_OPTIONS
                ),
                volume=0.5,
            )
            self.current = track
            self._next.clear()

            def after(err: Optional[Exception]) -> None:
                if err:
                    log.warning("Playback error: %s", err)
                self.bot.loop.call_soon_threadsafe(self._next.set)

            try:
                self.voice.play(source, after=after)
            except discord.ClientException as e:
                log.warning("Couldn't play: %s", e)
                self.current = None
                continue

            await self._say(f"Now playing {track.display} (requested by {track.requester})")
            await self._next.wait()
            self.current = None
