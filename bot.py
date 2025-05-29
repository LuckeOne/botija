import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# Carga de variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Opciones de yt-dlp con soporte de cookies
ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'cookies': 'cookies.txt',  # 🟡 Asegúrate de que este archivo esté presente
}
ffmpeg_opts = {
    'options': '-vn'
}
ytdl = yt_dlp.YoutubeDL(ytdl_opts)

# Intents y bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Cola de URLs por guild
queues: dict[int, asyncio.Queue] = {}

def is_url(string: str) -> bool:
    return string.startswith("http://") or string.startswith("https://")

async def get_audio_source(url: str):
    """Extrae la URL de audio con yt-dlp y la envuelve en FFmpegPCMAudio."""
    info = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
    # Si es playlist, devolvemos lista de URLs
    if 'entries' in info:
        return [entry['url'] for entry in info['entries'] if 'url' in entry]
    return discord.FFmpegPCMAudio(info['url'], **ffmpeg_opts)

async def play_next(ctx: commands.Context, vc: discord.VoiceClient):
    guild_id = ctx.guild.id
    queue = queues.get(guild_id)
    if not queue or queue.empty():
        return await vc.disconnect()

    url = await queue.get()
    extract_url = url if is_url(url) else f"ytsearch1:{url}"

    try:
        result = await get_audio_source(extract_url)
    except Exception as e:
        await ctx.send(f"❌ Error al reproducir: {e}")
        return await play_next(ctx, vc)

    if isinstance(result, list):
        for item in result:
            queue.put_nowait(item)
        return await play_next(ctx, vc)

    vc.play(result, after=lambda e: bot.loop.create_task(play_next(ctx, vc)))

@bot.command()
async def join(ctx: commands.Context):
    if not ctx.author.voice:
        return await ctx.send("❌ Conéctate a un canal de voz primero.")
    await ctx.author.voice.channel.connect()
    await ctx.send("✅ Me he unido al canal.")

@bot.command()
async def leave(ctx: commands.Context):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Adiós.")
    else:
        await ctx.send("❌ No estoy en ningún canal.")

@bot.command()
async def play(ctx: commands.Context, *, query: str):
    """Reproduce una URL o búsqueda de YouTube."""
    guild_id = ctx.guild.id
    queues.setdefault(guild_id, asyncio.Queue())
    queues[guild_id].put_nowait(query)
    await ctx.send(f"▶️ Encolada: **{query}**")

    vc = ctx.voice_client or await ctx.author.voice.channel.connect()
    if not vc.is_playing():
        await play_next(ctx, vc)

@bot.command()
async def skip(ctx: commands.Context):
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await ctx.send("⏭️ Saltando canción.")
    else:
        await ctx.send("❌ No hay reproducción activa.")

@bot.command(name="queue")
async def queue_cmd(ctx: commands.Context):
    queue = queues.get(ctx.guild.id)
    if not queue or queue.empty():
        return await ctx.send("❌ La cola está vacía.")
    items = list(queue._queue)
    msg = "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))
    await ctx.send(f"📃 Cola:\n{msg}")

@bot.command(name="stop")
async def stop_cmd(ctx: commands.Context):
    vc = ctx.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
        await ctx.send("🛑 Detenido y desconectado.")
    else:
        await ctx.send("❌ No estoy en un canal de voz.")

if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: Falta DISCORD_TOKEN")
        exit(1)
    bot.run(TOKEN)
