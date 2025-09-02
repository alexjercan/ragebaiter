import io
import os
import discord
import aiohttp
import asyncio

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TESTING_GUILD_ID = 1412415259683196970
RAGEBAITER_API_URL = os.getenv("RAGEBAITER_API_URL", "http://localhost:8000")

discord.opus.load_opus("libopus.so")
if not discord.opus.is_loaded():
    exit("Could not load opus library")

intents = discord.Intents.default()
intents.voice_states = True

bot = discord.Bot(intents=intents)
connections = {}


@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")


@bot.slash_command(guild_ids=[TESTING_GUILD_ID])
async def hello(ctx):
    print(f"Hello command invoked by {ctx.author}")
    await ctx.respond("Hello!")


@bot.slash_command(guild_ids=[TESTING_GUILD_ID])
async def join(ctx):
    if ctx.author.voice:
        print(f"Join command invoked by {ctx.author}")
        channel = ctx.author.voice.channel
        await channel.connect()
        await ctx.respond(f"Joined {channel.name}")
        print(f"Connected to voice channel: {channel.name}")
    else:
        print(
            f"Join command invoked by {ctx.author}, but they are not in a voice channel."
        )
        await ctx.respond("You are not in a voice channel.")


@bot.slash_command(guild_ids=[TESTING_GUILD_ID])
async def leave(ctx):
    print(f"Leave command invoked by {ctx.author}")
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.respond("Disconnected from the voice channel.")
        print("Disconnected from voice channel.")
    else:
        await ctx.respond("I am not in a voice channel.")
        print("Leave command invoked, but bot is not in a voice channel.")


@bot.slash_command(guild_ids=[TESTING_GUILD_ID])
async def record(ctx):
    print(f"Record command invoked by {ctx.author}")

    if ctx.guild.id in connections:
        print(f"Record command invoked by {ctx.author}, but already recording.")
        await ctx.respond("I am already recording in this guild.")
        return

    if ctx.voice_client is None:
        print(
            f"Record command invoked by {ctx.author}, but bot is not in a voice channel."
        )
        await ctx.respond(
            "I am not in a voice channel. Use /join to make me join a voice channel first."
        )
        return

    vc = ctx.voice_client
    connections.update({ctx.guild.id: vc})
    vc.start_recording(discord.sinks.WaveSink(), once_done, ctx.channel, vc)
    await ctx.respond("Started recording!")
    print(f"Started recording in guild: {ctx.guild.id}")


async def once_done(sink: discord.sinks, channel: discord.TextChannel, vc, *args):
    recorded_users = [f"<@{user_id}>" for user_id, audio in sink.audio_data.items()]
    files = [
        discord.File(audio.file, f"{user_id}.{sink.encoding}")
        for user_id, audio in sink.audio_data.items()
    ]
    await channel.send(
        f"finished recording audio for: {', '.join(recorded_users)}.", files=files
    )

    await send_audio_to_api(sink, vc)


async def send_audio_to_api(sink: discord.sinks, vc):
    form_data = aiohttp.FormData()
    for user_id, audio in sink.audio_data.items():
        # If audio.file is a file-like object or BytesIO
        audio.file.seek(0)  # Important: rewind the file pointer
        form_data.add_field(
            name="file",  # Field name expected by API
            value=audio.file,  # The BytesIO or file object
            filename=f"{user_id}.{sink.encoding}",
            content_type="audio/wav",  # or "audio/ogg", match your encoding
        )

    async with aiohttp.ClientSession() as session:
        async with session.post(RAGEBAITER_API_URL + "/bait", data=form_data) as resp:
            data = await resp.json()
            wav_id = data.get("id")
            async with session.get(RAGEBAITER_API_URL + f"/audio/{wav_id}") as wav_resp:
                if wav_resp.status == 200:
                    audio_bytes = await wav_resp.read()
                    await play_audio(vc, audio_bytes)
                    print("Playing synthesized audio...")
                else:
                    print(f"Failed to get synthesized audio, status code: {wav_resp.status}")


async def play_audio(vc, audio_bytes: bytes):
    """Play audio directly from bytes in a Discord voice channel."""
    audio_io = io.BytesIO(audio_bytes)
    audio_io.seek(0)
    source = discord.FFmpegPCMAudio(audio_io, pipe=True)
    source = discord.PCMVolumeTransformer(source)  # Optional: adjust volume if needed
    vc.play(source)

    while vc.is_playing():
        await asyncio.sleep(0.1)


@bot.command(guild_ids=[TESTING_GUILD_ID])
async def stop_recording(ctx):
    print(f"Stop recording command invoked by {ctx.author}")
    if ctx.guild.id not in connections:
        print(
            f"Stop recording command invoked by {ctx.author}, but no recording in progress."
        )
        await ctx.respond("I am not recording in this guild.")
        return

    vc = connections[ctx.guild.id]
    vc.stop_recording()
    del connections[ctx.guild.id]
    await ctx.delete()


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
