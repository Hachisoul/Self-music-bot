# Self-music-bot

A Discord music bot that plays YouTube, SoundCloud and Spotify links in a voice channel, using slash commands.

## Commands

| Command | What it does |
| --- | --- |
| `/play <link or search>` | Joins your voice channel and plays a song or playlist. Plain words search YouTube. |
| `/pause` | Pauses the current song. |
| `/resume` | Resumes a paused song. |
| `/skip` | Skips to the next song in the queue. |
| `/stop` | Stops playback and clears the queue (stays in the channel). |
| `/queue` | Shows what's playing and the next 10 songs. |
| `/leave` | Disconnects from the voice channel. |

You need to be in the same voice channel as the bot to control it. The bot leaves on its own after 5 minutes with nothing playing.

### Supported links

- **YouTube**: videos and playlists (also YouTube Music links).
- **SoundCloud**: tracks and sets/playlists.
- **Spotify**: tracks, albums and playlists. Spotify doesn't let bots stream its audio, so the bot reads the song names from Spotify and plays the best match from YouTube. Matches are usually right but can occasionally pick a cover or live version. Spotify's own editorial/algorithmic playlists (like "Today's Top Hits") are blocked by Spotify's API for new apps, but user-made playlists work.

Playlists are capped at 100 tracks per `/play`.

## Setup

### 1. Install the requirements

- **Python 3.10 or newer**
- **FFmpeg**, available on your PATH
  - Windows: `winget install Gyan.FFmpeg` (then open a new terminal)
  - macOS: `brew install ffmpeg`
  - Debian/Ubuntu: `sudo apt install ffmpeg`
- **Deno** (recommended): recent versions of yt-dlp need a JavaScript runtime to read YouTube reliably. Install from https://deno.com (`winget install DenoLand.Deno` / `brew install deno`).

Then, in this folder:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Create the Discord bot

1. Go to https://discord.com/developers/applications and click **New Application**.
2. Open **Bot**, click **Reset Token**, and copy the token. Keep it secret.
3. Privileged intents are **not** needed (the bot uses slash commands and the default voice states intent).
4. Open **OAuth2 → URL Generator**, tick the scopes `bot` and `applications.commands`, and the bot permissions **View Channels**, **Send Messages**, **Embed Links**, **Connect** and **Speak**.
5. Open the generated URL and add the bot to your server.

### 3. (Optional) Spotify credentials

Only needed if you want Spotify links to work.

1. Go to https://developer.spotify.com/dashboard and create an app (any redirect URI, e.g. `http://127.0.0.1:8888/callback`; it isn't used).
2. Copy the **Client ID** and **Client Secret**.

### 4. Configure and run

Copy `.env.example` to `.env` and fill it in:

```
DISCORD_TOKEN=your-bot-token
SPOTIFY_CLIENT_ID=optional
SPOTIFY_CLIENT_SECRET=optional
DEV_GUILD_ID=optional-your-server-id
```

`DEV_GUILD_ID` makes slash commands show up instantly in that one server. Without it, commands are registered globally, which can take up to an hour the first time.
(To get a server ID: enable Developer Mode in Discord settings → Advanced, then right-click the server → Copy Server ID.)

Start the bot:

```bash
python bot.py
```

## Troubleshooting

- **Commands don't appear**: set `DEV_GUILD_ID`, restart, and reload Discord (Ctrl+R).
- **"Couldn't load that link"** for YouTube: update yt-dlp (`pip install -U yt-dlp`), make sure Deno is installed. YouTube changes often and yt-dlp releases fixes quickly.
- **Bot joins but no sound**: check that FFmpeg works (`ffmpeg -version`) and the bot has the **Speak** permission.

## Project layout

```
bot.py            slash commands and startup
music/sources.py  turns links/searches into tracks (yt-dlp, Spotify lookup)
music/player.py   per-server queue and playback
```
