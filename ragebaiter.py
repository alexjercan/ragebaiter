import io
import os
import logging
import asyncio
import aiohttp
import discord

# ----------------------------
# Configuration
# ----------------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TESTING_GUILD_ID = int(os.getenv("TESTING_GUILD_ID", "1412415259683196970"))
RAGEBAITER_API_URL = os.getenv("RAGEBAITER_API_URL", "http://localhost:8000")

# ----------------------------
# Logging setup
# ----------------------------
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ----------------------------
# Load Opus library for voice
# ----------------------------
discord.opus.load_opus("libopus.so")
if not discord.opus.is_loaded():
    logger.critical("Could not load opus library")
    exit(1)

# ----------------------------
# Discord bot setup
# ----------------------------
intents = discord.Intents.default()
intents.voice_states = True
bot = discord.Bot(intents=intents)
connections = {}  # Tracks active recordings per guild


# ----------------------------
# Bot events
# ----------------------------
@bot.event
async def on_ready():
    """Triggered when the bot is ready."""
    logger.info(f"Logged in as {bot.user}")


# ----------------------------
# Slash commands
# ----------------------------
@bot.slash_command(guild_ids=[TESTING_GUILD_ID])
async def hello(ctx):
    """Simple hello command for testing."""
    logger.info(f"Hello command invoked by {ctx.author}")
    await ctx.respond("Hello!")


@bot.slash_command(guild_ids=[TESTING_GUILD_ID])
async def join(ctx):
    """Join the voice channel of the user."""
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        logger.info(f"{ctx.author} requested bot to join {channel.name}")
        await channel.connect()
        await ctx.respond(f"Joined {channel.name}")
        logger.info(f"Connected to voice channel: {channel.name}")
    else:
        logger.warning(f"{ctx.author} tried to join, but is not in a voice channel")
        await ctx.respond("You are not in a voice channel.")


@bot.slash_command(guild_ids=[TESTING_GUILD_ID])
async def leave(ctx):
    """Leave the current voice channel."""
    logger.info(f"Leave command invoked by {ctx.author}")
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.respond("Disconnected from the voice channel.")
        logger.info("Disconnected from voice channel.")
    else:
        logger.warning("Bot is not in a voice channel")
        await ctx.respond("I am not in a voice channel.")


@bot.slash_command(guild_ids=[TESTING_GUILD_ID])
async def record(ctx):
    """Start recording audio in the current voice channel."""
    logger.info(f"Record command invoked by {ctx.author}")

    if ctx.guild.id in connections:
        logger.warning("Already recording in this guild")
        await ctx.respond("I am already recording in this guild.")
        return

    if not ctx.voice_client:
        logger.warning("Bot is not in a voice channel")
        await ctx.respond("Use /join to make me join a voice channel first.")
        return

    vc = ctx.voice_client
    connections[ctx.guild.id] = vc
    vc.start_recording(discord.sinks.WaveSink(), once_done, ctx.channel, vc)
    await ctx.respond("Started recording!")
    logger.info(f"Started recording in guild: {ctx.guild.id}")


@bot.command(guild_ids=[TESTING_GUILD_ID])
async def stop_recording(ctx):
    """Stop recording audio."""
    logger.info(f"Stop recording command invoked by {ctx.author}")

    if ctx.guild.id not in connections:
        logger.warning("No active recording in this guild")
        await ctx.respond("I am not recording in this guild.")
        return

    vc = connections[ctx.guild.id]
    vc.stop_recording()
    del connections[ctx.guild.id]
    await ctx.delete()
    logger.info("Stopped recording and cleared connection")


# ----------------------------
# Recording callbacks
# ----------------------------
async def once_done(sink: discord.sinks, channel: discord.TextChannel, vc, *args):
    """Callback executed after recording is finished."""
    recorded_users = [f"<@{user_id}>" for user_id, audio in sink.audio_data.items()]
    files = [
        discord.File(audio.file, f"{user_id}.{sink.encoding}")
        for user_id, audio in sink.audio_data.items()
    ]

    await channel.send(
        f"Finished recording audio for: {', '.join(recorded_users)}.", files=files
    )
    logger.info(f"Finished recording for users: {recorded_users}")

    await send_audio_to_api(sink, vc)


async def send_audio_to_api(sink: discord.sinks, vc):
    """Send recorded audio to the RageBaiter API and play synthesized audio."""
    form_data = aiohttp.FormData()
    for user_id, audio in sink.audio_data.items():
        audio.file.seek(0)
        form_data.add_field(
            name="file",
            value=audio.file,
            filename=f"{user_id}.{sink.encoding}",
            content_type="audio/wav",
        )

    async with aiohttp.ClientSession() as session:
        async with session.post(RAGEBAITER_API_URL + "/bait", data=form_data) as resp:
            if resp.status != 200:
                logger.error(f"Failed to send audio to API, status: {resp.status}")
                return

            data = await resp.json()
            wav_id = data.get("id")
            async with session.get(RAGEBAITER_API_URL + f"/audio/{wav_id}") as wav_resp:
                if wav_resp.status == 200:
                    audio_bytes = await wav_resp.read()
                    await play_audio(vc, audio_bytes)
                    logger.info("Playing synthesized audio")
                else:
                    logger.error(
                        f"Failed to retrieve synthesized audio, status: {wav_resp.status}"
                    )


async def play_audio(vc, audio_bytes: bytes):
    """Play audio directly from bytes in a Discord voice channel."""
    audio_io = io.BytesIO(audio_bytes)
    audio_io.seek(0)
    source = discord.FFmpegPCMAudio(audio_io, pipe=True)
    source = discord.PCMVolumeTransformer(source)
    vc.play(source)

    while vc.is_playing():
        await asyncio.sleep(0.1)


# ----------------------------
# Main entry
# ----------------------------
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
