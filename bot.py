import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp as youtube_dl

# Carga de variables de entorno
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configuración de intents y bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Cola global de canciones por guild
queues: dict[int, asyncio.Queue] = {}

# Opciones de yt-dlp para buscar y extraer sin descargar
ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'extract_flat': 'in_playlist',
    'default_search': 'ytsearch',  # ← aquí permitimos búsqueda por texto
}
ffmpeg_opts = {
    'options': '-vn'
}
ytdl = youtube_dl.YoutubeDL(ytdl_opts)

class YTDLSource(discord.PCMVolumeTransformer):
    """Fuente de audio extraída con yt-dlp."""
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url   = data.get('url')

    @classmethod
    async def from_url(cls, url: str, *, loop: asyncio.AbstractEventLoop):
        """Extrae información de URL o búsqueda y devuelve un source o lista de urls."""
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        # Si es playlist (lista de dicts), devolvemos la lista de entradas
        if 'entries' in data:
            # Cada entry puede no tener la url directa, así que reconstruimos URLs de búsqueda
            return [f"ytsearch:{entry['title']}" for entry in data['entries']]
        # Para un único video en data
        source = discord.FFmpegPCMAudio(data['url'], **ffmpeg_opts)
        return cls(source, data=data)

async def play_next(ctx: commands.Context, vc: discord.VoiceClient):
    """Función recursiva para reproducir la siguiente canción en la cola."""
    guild_id = ctx.guild.id
    queue = queues.get(guild_id)
    if not queue or queue.empty():
        return await vc.disconnect()
    # Obtenemos la siguiente URL o búsqueda
    item = await queue.get()
    # Si el item es un "ytsearch:", extraemos realmente un video
    if item.startswith("ytsearch:"):
        info = await YTDLSource.from_url(item, loop=bot.loop)
        # ytsearch devuelve lista de búsquedas, tomamos el primero
        info = info[0] if isinstance(info, list) else info
    else:
        info = await YTDLSource.from_url(item, loop=bot.loop)
    vc.play(info, after=lambda e: bot.loop.create_task(play_next(ctx, vc)))

@bot.command()
async def join(ctx: commands.Context):
    """Une el bot al canal de voz del autor."""
    if not ctx.author.voice:
        return await ctx.send("❌ Conéctate a un canal de voz primero.")
    vc = ctx.voice_client or await ctx.author.voice.channel.connect()
    await ctx.send("✅ Me he unido al canal.")

@bot.command()
async def leave(ctx: commands.Context):
    """Desconecta el bot del canal de voz."""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Adiós.")
    else:
        await ctx.send("❌ No estoy en ningún canal de voz.")

@bot.command()
async def play(ctx: commands.Context, *, query: str):
    """Reproduce un video o playlist de YouTube por URL o por búsqueda."""
    vc = ctx.voice_client or await ctx.author.voice.channel.connect()
    guild_id = ctx.guild.id
    queues.setdefault(guild_id, asyncio.Queue())

    # Extraemos la info; gracias a default_search acepta texto
    info = await YTDLSource.from_url(query, loop=bot.loop)

    # Si devuelve lista, es playlist
    if isinstance(info, list):
        await ctx.send(f"📜 Encolando playlist de {len(info)} canciones...")
        for item in info:
            queues[guild_id].put_nowait(item)
    else:
        await ctx.send(f"▶️ Encolada: **{info.title}**")
        queues[guild_id].put_nowait(query)

    # Si no está reproduciendo, lanza la cola
    if not vc.is_playing():
        await play_next(ctx, vc)

@bot.command()
async def skip(ctx: commands.Context):
    """Salta la canción actual."""
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await ctx.send("⏭️ Saltando canción.")
    else:
        await ctx.send("❌ No estoy reproduciendo nada.")

@bot.command()
async def queue_cmd(ctx: commands.Context):
    """Muestra las próximas canciones en la cola."""
    queue = queues.get(ctx.guild.id)
    if not queue or queue.empty():
        return await ctx.send("❌ La cola está vacía.")
    items = list(queue._queue)
    msg = "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))
    await ctx.send(f"📃 Próximas canciones:\n{msg}")

@bot.command(name="stop")
async def stop_cmd(ctx: commands.Context):
    """Detiene la reproducción y desconecta."""
    vc = ctx.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
        await ctx.send("🛑 Detenido y desconectado.")
    else:
        await ctx.send("❌ No estoy en un canal de voz.")

if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: Falta la variable DISCORD_TOKEN")
        exit(1)
    bot.run(TOKEN)