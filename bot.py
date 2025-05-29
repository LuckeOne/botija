import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

YTDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'ignoreerrors': True,
    'cookies': 'cookies.txt',
    'default_search': 'ytsearch',
}
FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Una cola y una tarea de reproducción por guild
players: dict[int, 'MusicPlayer'] = {}

class MusicPlayer:
    def __init__(self, ctx: commands.Context):
        self.ctx = ctx
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self.play_task = bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        vc = await self.ctx.author.voice.channel.connect() if not self.ctx.guild.voice_client else self.ctx.guild.voice_client

        while True:
            track = await self.queue.get()
            # Obtener URL directa + headers
            info = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(track['webpage_url'], download=False))
            if not info or 'formats' not in info:
                continue

            # Elegir mejor formato
            fmt_candidates = [f for f in info['formats'] if f.get('url')]
            if not fmt_candidates:
                continue
            fmt = max(fmt_candidates, key=lambda f: f.get('abr') or 0)
            url = fmt['url']
            headers = fmt.get('http_headers', {})
            header_str = "".join(f"{k}: {v}\r\n" for k,v in headers.items())
            before = f"-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -headers \"{header_str}\""
            source = discord.FFmpegPCMAudio(url, before_options=before, options='-vn')

            # Embed
            dur = track.get('duration') or 0
            m,s = divmod(dur, 60)
            embed = discord.Embed(
                title=track['title'],
                url=track['webpage_url'],
                color=discord.Color.green(),
                description=f"**Uploader:** {track['uploader']}\n**Duración:** {m}:{s:02d}"
            )
            thumb = track.get('thumbnail')
            if thumb:
                embed.set_thumbnail(url=thumb)

            # Reproducir y esperar hasta que termine
            vc.play(source)
            await self.ctx.send(embed=embed)
            while vc.is_playing() or vc.is_paused():
                await asyncio.sleep(1)

            if self.queue.empty():
                await vc.disconnect()
                break

    def enqueue(self, track: dict):
        self.queue.put_nowait(track)

@bot.command()
async def play(ctx: commands.Context, *, query: str):
    if not ctx.author.voice:
        return await ctx.send("❌ Debes estar en un canal de voz.")
    # Obtener o crear player
    player = players.get(ctx.guild.id)
    if not player:
        player = MusicPlayer(ctx)
        players[ctx.guild.id] = player

    # Mensaje de carga
    loading = await ctx.send("⏳ Cargando pistas, por favor espera...")
    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
    tracks = []
    def build(e):
        return {
            'webpage_url': e.get('webpage_url'),
            'title': e.get('title'),
            'uploader': e.get('uploader'),
            'duration': e.get('duration'),
            'thumbnail': e.get('thumbnail')
        }

    if data and 'entries' in data:
        for e in data['entries'] or []:
            if e and e.get('webpage_url'):
                tracks.append(build(e))
    elif data:
        tracks.append(build(data))

    for t in tracks:
        player.enqueue(t)

    await loading.edit(content=f"✅ Encoladas {len(tracks)} pista(s).")

@bot.command()
async def skip(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await ctx.send("⏭️ Saltado.")
    else:
        await ctx.send("❌ Nada que saltar.")

@bot.command()
async def stop(ctx: commands.Context):
    player = players.pop(ctx.guild.id, None)
    vc = ctx.guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
    if player:
        player.play_task.cancel()
    await ctx.send("⏹️ Detenido y desconectado.")

@bot.event
async def on_ready():
    print(f"Bot listo: {bot.user}")

bot.run(TOKEN)
