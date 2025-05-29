import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# Carga de variables de entorno
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configuración de yt-dlp para manejar playlists y errores
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'ignoreerrors': True,       # Ignorar videos no disponibles
    'cookies': 'cookies.txt',   # Cookies para autenticación
    'default_search': 'ytsearch',
    'extract_flat': False       # Obtener metadata completa
}
FFMPEG_OPTS = {'options': '-vn'}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

# Inicialización del bot
token = TOKEN
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Cola de pistas por guild
t_queues: dict[int, asyncio.Queue] = {}

async def enqueue_tracks(ctx: commands.Context, query: str) -> list[dict]:
    """Extrae pistas de URL o búsqueda, maneja playlists y omite errores."""
    info = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
    tracks = []
    if not info:
        return tracks
    entries = info.get('entries') or [info]
    for entry in entries:
        if not entry or entry.get('url') is None:
            continue
        tracks.append({
            'title': entry.get('title'),
            'webpage_url': entry.get('webpage_url'),
            'url': entry.get('url'),
            'duration': entry.get('duration', 0),
            'uploader': entry.get('uploader'),
            'thumbnail': entry.get('thumbnail')
        })
    q = t_queues.setdefault(ctx.guild.id, asyncio.Queue())
    for track in tracks:
        await q.put(track)
    return tracks

async def play_next(ctx: commands.Context):
    """Reproduce la siguiente pista, o desconecta si la cola está vacía."""
    queue = t_queues.get(ctx.guild.id)
    vc = ctx.guild.voice_client
    if not queue or queue.empty():
        if vc:
            await vc.disconnect()
        return

    track = await queue.get()
    source = discord.FFmpegPCMAudio(track['url'], **FFMPEG_OPTS)

    # Formatear duración
    dur = track['duration']
    mins, secs = divmod(dur, 60)
    duration_str = f"{mins}:{secs:02d}"

    embed = discord.Embed(
        title=track['title'],
        url=track['webpage_url'],
        color=discord.Color.blurple(),
        description=(f"**Uploader:** {track['uploader']}\n"
                     f"**Duration:** {duration_str}")
    )
    if track['thumbnail']:
        embed.set_thumbnail(url=track['thumbnail'])

    # Vista con botones
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary, custom_id="pause"))
    view.add_item(discord.ui.Button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, custom_id="skip"))
    view.add_item(discord.ui.Button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="stop"))

    def after_play(error):
        coro = play_next(ctx)
        fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
    vc.play(source, after=after_play)

    msg = await ctx.send(embed=embed, view=view)

    # Interacción con botones
    async def interaction_listener(interaction: discord.Interaction):
        if interaction.message.id != msg.id:
            return
        vc = ctx.guild.voice_client
        cid = interaction.data.get('custom_id')
        if cid == 'pause':
            if vc.is_paused():
                vc.resume()
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                vc.pause()
                await interaction.response.edit_message(embed=embed, view=view)
        elif cid == 'skip':
            vc.stop()
            await interaction.response.send_message("⏭️ Saltado", ephemeral=True)
        elif cid == 'stop':
            vc.stop()
            await vc.disconnect()
            t_queues.pop(ctx.guild.id, None)
            await interaction.response.send_message("⏹️ Detenido", ephemeral=True)

    bot.add_listener(interaction_listener, 'on_interaction')

@bot.command()
async def join(ctx: commands.Context):
    if ctx.author.voice:
        await ctx.author.voice.channel.connect()
        await ctx.send("✅ Unido al canal.")
    else:
        await ctx.send("❌ Conéctate a un canal de voz primero.")

@bot.command()
async def leave(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc:
        await vc.disconnect()
        t_queues.pop(ctx.guild.id, None)
        await ctx.send("👋 Desconectado y cola limpia.")
    else:
        await ctx.send("❌ No estoy en un canal.")

@bot.command()
async def play(ctx: commands.Context, *, query: str):
    if not ctx.author.voice:
        return await ctx.send("❌ Debes estar en un canal de voz.")
    vc = ctx.guild.voice_client or await ctx.author.voice.channel.connect()
    tracks = await enqueue_tracks(ctx, query)
    if not tracks:
        return await ctx.send("❌ No se encontró ninguna pista.")
    await ctx.send(f"📜 Encoladas {len(tracks)} pista(s).")
    if not vc.is_playing():
        await play_next(ctx)

@bot.command()
async def skip(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await ctx.send("⏭️ Saltado.")
    else:
        await ctx.send("❌ No estoy reproduciendo.")

@bot.command(name="queue")
async def queue_cmd(ctx: commands.Context):
    q = t_queues.get(ctx.guild.id)
    if not q or q.empty():
        return await ctx.send("❌ La cola está vacía.")
    titles = [t['title'] for t in list(q._queue)]
    msg = "\n".join(f"{i+1}. {title}" for i,title in enumerate(titles))
    await ctx.send(f"📃 Próximas canciones:\n{msg}")

@bot.command(name="stop")
async def stop_cmd(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
        t_queues.pop(ctx.guild.id, None)
        await ctx.send("🛑 Detenido y desconectado.")
    else:
        await ctx.send("❌ No estoy en un canal.")

@bot.event
async def on_ready():
    print(f"Bot listo: {bot.user}")

if __name__ == '__main__':
    bot.run(token)
