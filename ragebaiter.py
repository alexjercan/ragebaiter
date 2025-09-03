import aiohttp
import asyncio
import discord
import dotenv
import io
import logging
import os
import random

dotenv.load_dotenv()

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

connections = {}  # guild_id -> voice client
ragebait_tasks = {}  # guild_id -> asyncio.Task


# ----------------------------
# Bot events
# ----------------------------
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")


# ----------------------------
# Commands
# ----------------------------
@bot.slash_command(guild_ids=[TESTING_GUILD_ID])
async def hello(ctx):
    await ctx.respond("Hello!")


@bot.slash_command(guild_ids=[TESTING_GUILD_ID])
async def ragebait(ctx):
    """Start the ragebait loop in your voice channel."""
    logger.info(f"Ragebait command invoked by {ctx.author}")

    if ctx.guild.id in ragebait_tasks:
        await ctx.respond("⚠️ Ragebait is already running in this server.")
        return

    if not ctx.author.voice:
        await ctx.respond("❌ You need to be in a voice channel to use this.")
        return

    # Join voice if not already in
    if ctx.voice_client is None:
        vc = await ctx.author.voice.channel.connect()
    else:
        vc = ctx.voice_client

    connections[ctx.guild.id] = vc
    await ctx.respond("🎙️ Ragebait started! I'll record randomly every few minutes.")

    # Start background task
    task = asyncio.create_task(ragebait_loop(ctx.guild.id, ctx.channel, vc))
    ragebait_tasks[ctx.guild.id] = task


@bot.slash_command(guild_ids=[TESTING_GUILD_ID])
async def stopragebait(ctx):
    """Stop the ragebait loop."""
    if ctx.guild.id not in ragebait_tasks:
        await ctx.respond("⚠️ Ragebait is not running here.")
        return

    ragebait_tasks[ctx.guild.id].cancel()
    del ragebait_tasks[ctx.guild.id]
    await ctx.respond("🛑 Ragebait stopped.")


# ----------------------------
# Ragebait loop
# ----------------------------
async def ragebait_loop(guild_id, channel, vc):
    try:
        while True:
            wait_time = random.randint(300, 900)  # 5–15 min
            logger.info(
                f"Waiting {wait_time}s before next recording in guild {guild_id}"
            )
            await asyncio.sleep(wait_time)

            record_duration = random.randint(10, 60)  # 10–60 sec
            logger.info(f"Recording {record_duration}s in guild {guild_id}")

            sink = discord.sinks.WaveSink()
            vc.start_recording(sink, once_done, channel, vc)

            await asyncio.sleep(record_duration)
            if vc.recording:
                vc.stop_recording()
    except asyncio.CancelledError:
        logger.info(f"Ragebait loop cancelled in guild {guild_id}")


# ----------------------------
# Recording callbacks
# ----------------------------
async def once_done(sink: discord.sinks, channel: discord.TextChannel, vc, *args):
    """Callback executed after recording is finished."""
    recorded_users = [f"<@{user_id}>" for user_id, audio in sink.audio_data.items()]
    logger.info(f"Finished recording for users: {recorded_users}")

    # Merge all user audios
    merged_audio = None
    for user_id, audio in sink.audio_data.items():
        # TODO: make this ok
        merged_audio = audio.file
        break

    if merged_audio is None:
        logger.warning("No audio recorded.")
        return

    # Send merged audio
    await send_audio_to_api(merged_audio, vc)


async def send_audio_to_api(file_obj, vc):
    form_data = aiohttp.FormData()
    form_data.add_field(
        name="file",
        value=file_obj,
        filename="conversation.wav",
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
                else:
                    logger.error(
                        f"Failed to retrieve synthesized audio, status: {wav_resp.status}"
                    )


async def play_audio(vc, audio_bytes: bytes):
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
