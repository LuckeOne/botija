import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp as youtube_dl

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Cola global de canciones por guild
queues = {}

ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'extract_flat': 'in_playlist'
}
ffmpeg_opts = {
    'options': '-vn'
}
ytdl = youtube_dl.YoutubeDL(ytdl_opts)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop):
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        # Si es playlist, devolvemos la lista de entries
        if 'entries' in data:
            return data['entries']
        return cls(discord.FFmpegPCMAudio(data['url'], **ffmpeg_opts), data=data)

@bot.command()
async def join(ctx):
    if not ctx.author.voice:
        return await ctx.send("❌ Conéctate a un canal de voz primero.")
    await ctx.author.voice.channel.connect()
    await ctx.send("✅ Me he unido al canal.")

@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Adiós.")
    else:
        await ctx.send("❌ No estoy en ningún canal.")

@bot.command()
async def play(ctx, *, url: str):
    """Reproduce un video o playlist de YouTube."""
    vc = ctx.voice_client or await ctx.author.voice.channel.connect()
    guild_id = ctx.guild.id
    queues.setdefault(guild_id, asyncio.Queue())

    info = await YTDLSource.from_url(url, loop=bot.loop)
    # Si es playlist, info es lista de dicts
    if isinstance(info, list):
        await ctx.send(f"📜 Encolando playlist de {len(info)} canciones...")
        for entry in info:
            queues[guild_id].put_nowait(entry['url'])
    else:
        await ctx.send(f"▶️ Encolada: **{info.title}**")
        queues[guild_id].put_nowait(url)

    if not vc.is_playing():
        await play_next(ctx, vc)

async def play_next(ctx, vc):
    guild_id = ctx.guild.id
    try:
        url = await queues[guild_id].get()
    except asyncio.QueueEmpty:
        await vc.disconnect()
        return

    # Extraer y reproducir
    player = await YTDLSource.from_url(url, loop=bot.loop)
    vc.play(player, after=lambda e: bot.loop.create_task(play_next(ctx, vc)))

@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭️ Saltando canción.")
    else:
        await ctx.send("❌ No estoy reproduciendo nada.")

@bot.command()
async def queue(ctx):
    q = queues.get(ctx.guild.id)
    if not q or q.empty():
        return await ctx.send("❌ La cola está vacía.")
    items = list(q._queue)
    msg = "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))
    await ctx.send(f"📃 Próximas:\n{msg}")

@bot.command()
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        await ctx.send("🛑 Detenido y desconectado.")
    else:
        await ctx.send("❌ No estoy en un canal.")

bot.run(TOKEN)
