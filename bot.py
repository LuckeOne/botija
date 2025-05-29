import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp
import logging

# Configuración de logging
logging.basicConfig(level=logging.INFO)

# Cargar el token del archivo .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logging.error("❌ DISCORD_TOKEN no encontrado en el archivo .env.")
    exit(1)

# Opciones de descarga de audio
ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'cookies': 'cookies.txt',  # Asegúrate de que este archivo esté en la raíz
}
ffmpeg_opts = {
    'options': '-vn'
}
ytdl = yt_dlp.YoutubeDL(ytdl_opts)

# Intents y creación del bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Cola de reproducción por servidor
queues: dict[int, asyncio.Queue] = {}

def is_url(string: str) -> bool:
    return string.startswith("http://") or string.startswith("https://")

async def get_audio_source(url: str):
    """Extrae información de audio con yt-dlp y devuelve un objeto FFmpegPCMAudio."""
    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
    if 'entries' in data:
        return [entry['url'] for entry in data['entries'] if 'url' in entry]
    return discord.FFmpegPCMAudio(data['url'], **ffmpeg_opts)

async def play_next(ctx: commands.Context, vc: discord.VoiceClient):
    guild_id = ctx.guild.id
    queue = queues.get(guild_id)

    if not queue or queue.empty():
        await ctx.send("📭 La cola ha terminado.")
        return await vc.disconnect()

    next_item = await queue.get()
    search_query = next_item if is_url(next_item) else f"ytsearch1:{next_item}"

    try:
        result = await get_audio_source(search_query)
    except Exception as e:
        await ctx.send(f"❌ Error al reproducir: {e}")
        return await play_next(ctx, vc)

    if isinstance(result, list):
        for entry in result:
            queue.put_nowait(entry)
        return await play_next(ctx, vc)

    vc.play(result, after=lambda e: bot.loop.create_task(play_next(ctx, vc)))

@bot.event
async def on_ready():
    logging.info(f"✅ Bot conectado como {bot.user}")

@bot.command()
async def join(ctx: commands.Context):
    if ctx.voice_client:
        return await ctx.send("✅ Ya estoy en el canal de voz.")
    if not ctx.author.voice:
        return await ctx.send("❌ Debes estar en un canal de voz primero.")
    await ctx.author.voice.channel.connect()
    await ctx.send("✅ Me he unido al canal de voz.")

@bot.command()
async def leave(ctx: commands.Context):
    vc = ctx.voice_client
    if vc:
        await vc.disconnect()
        await ctx.send("👋 Desconectado del canal.")
    else:
        await ctx.send("❌ No estoy conectado a un canal de voz.")

@bot.command()
async def play(ctx: commands.Context, *, query: str):
    """Agrega una canción a la cola y reproduce si está libre."""
    guild_id = ctx.guild.id
    queues.setdefault(guild_id, asyncio.Queue())
    queues[guild_id].put_nowait(query)
    await ctx.send(f"▶️ Encolado: **{query}**")

    vc = ctx.voice_client
    if not vc:
        if not ctx.author.voice:
            return await ctx.send("❌ Debes estar en un canal de voz para reproducir música.")
        vc = await ctx.author.voice.channel.connect()

    if not vc.is_playing():
        await play_next(ctx, vc)

@bot.command()
async def skip(ctx: commands.Context):
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await ctx.send("⏭️ Canción saltada.")
    else:
        await ctx.send("❌ No hay nada reproduciéndose.")

@bot.command(name="queue")
async def queue_cmd(ctx: commands.Context):
    queue = queues.get(ctx.guild.id)
    if not queue or queue.empty():
        return await ctx.send("📭 La cola está vacía.")
    
    # Copia segura del contenido de la cola
    items = list(queue._queue)  # No recomendado acceder directamente, pero no hay alternativa oficial
    formatted = "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))
    await ctx.send(f"🎶 Cola actual:\n{formatted}")

@bot.command(name="stop")
async def stop_cmd(ctx: commands.Context):
    vc = ctx.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
        await ctx.send("🛑 Reproducción detenida y bot desconectado.")
    else:
        await ctx.send("❌ No estoy en un canal de voz.")
