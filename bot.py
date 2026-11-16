"""Discord music bot: YouTube, SoundCloud and Spotify links via slash commands."""

from __future__ import annotations

import logging
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from music.player import GuildPlayer
from music.sources import SourceError, resolve

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

intents = discord.Intents.default()  # includes the voice_states intent we need
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
players: dict[int, GuildPlayer] = {}


def get_player(guild: discord.Guild) -> GuildPlayer:
    if guild.id not in players:
        players[guild.id] = GuildPlayer(bot, guild)
    return players[guild.id]


def user_channel(interaction: discord.Interaction) -> Optional[discord.VoiceChannel]:
    state = getattr(interaction.user, "voice", None)
    return state.channel if state else None


async def require_same_channel(interaction: discord.Interaction) -> Optional[GuildPlayer]:
    """Return the player if the bot is connected and the user is in its channel."""
    vc = interaction.guild.voice_client if interaction.guild else None
    if not vc:
        await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)
        return None
    if user_channel(interaction) != vc.channel:
        await interaction.response.send_message(
            f"Join {vc.channel.mention} to control the music.", ephemeral=True
        )
        return None
    return get_player(interaction.guild)


@bot.event
async def on_ready():
    guild_id = os.getenv("DEV_GUILD_ID")
    if guild_id:
        guild = discord.Object(id=int(guild_id))
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
    else:
        synced = await bot.tree.sync()
    logging.info("Logged in as %s, synced %d commands", bot.user, len(synced))


@bot.event
async def on_voice_state_update(member: discord.Member, before, after):
    # Clean up if the bot was disconnected (kicked, moved out, etc.).
    if member.id == bot.user.id and before.channel and not after.channel:
        player = players.pop(member.guild.id, None)
        if player:
            await player.destroy()


@bot.tree.command(description="Play a song or playlist from YouTube, SoundCloud or Spotify, or search YouTube")
@app_commands.describe(query="A link, or words to search YouTube for")
@app_commands.guild_only()
async def play(interaction: discord.Interaction, query: str):
    channel = user_channel(interaction)
    if not channel:
        await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
        return
    vc = interaction.guild.voice_client
    if vc and vc.channel != channel:
        await interaction.response.send_message(
            f"I'm already playing in {vc.channel.mention}.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)
    try:
        tracks = await resolve(query, interaction.user.display_name)
    except SourceError as e:
        await interaction.followup.send(str(e))
        return

    if not vc:
        await channel.connect(self_deaf=True)
    player = get_player(interaction.guild)
    player.text_channel = interaction.channel
    was_busy = player.current is not None or bool(player.queue)
    player.add(tracks)

    if len(tracks) == 1:
        msg = f"Queued {tracks[0].display}" if was_busy else f"Starting {tracks[0].display}"
    else:
        msg = f"Queued **{len(tracks)}** tracks."
    await interaction.followup.send(msg, suppress_embeds=True)


@bot.tree.command(description="Pause the current song")
@app_commands.guild_only()
async def pause(interaction: discord.Interaction):
    if not (player := await require_same_channel(interaction)):
        return
    if player.voice.is_playing():
        player.voice.pause()
        await interaction.response.send_message("Paused.")
    else:
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)


@bot.tree.command(description="Resume the paused song")
@app_commands.guild_only()
async def resume(interaction: discord.Interaction):
    if not (player := await require_same_channel(interaction)):
        return
    if player.voice.is_paused():
        player.voice.resume()
        await interaction.response.send_message("Resumed.")
    else:
        await interaction.response.send_message("Nothing is paused.", ephemeral=True)


@bot.tree.command(description="Skip to the next song")
@app_commands.guild_only()
async def skip(interaction: discord.Interaction):
    if not (player := await require_same_channel(interaction)):
        return
    if player.skip():
        await interaction.response.send_message("Skipped.")
    else:
        await interaction.response.send_message("Nothing to skip.", ephemeral=True)


@bot.tree.command(description="Stop playback and clear the queue")
@app_commands.guild_only()
async def stop(interaction: discord.Interaction):
    if not (player := await require_same_channel(interaction)):
        return
    player.stop()
    await interaction.response.send_message("Stopped and cleared the queue.")


@bot.tree.command(description="Show what's playing and what's next")
@app_commands.guild_only()
async def queue(interaction: discord.Interaction):
    player = players.get(interaction.guild.id)
    if not player or (not player.current and not player.queue):
        await interaction.response.send_message("The queue is empty.", ephemeral=True)
        return
    lines = []
    if player.current:
        state = " (paused)" if player.voice and player.voice.is_paused() else ""
        lines.append(f"**Now playing{state}:** {player.current.display}")
    for i, track in enumerate(player.queue[:10], start=1):
        lines.append(f"`{i}.` {track.display}")
    if len(player.queue) > 10:
        lines.append(f"...and {len(player.queue) - 10} more.")
    embed = discord.Embed(title="Queue", description="\n".join(lines), color=discord.Color.blurple())
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Leave the voice channel")
@app_commands.guild_only()
async def leave(interaction: discord.Interaction):
    if not (player := await require_same_channel(interaction)):
        return
    players.pop(interaction.guild.id, None)
    await player.destroy()
    await interaction.response.send_message("Bye!")


def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Set DISCORD_TOKEN in a .env file (see .env.example).")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
