import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# Carga de configuración
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# yt-dlp opts
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'ignoreerrors': True,
    'cookies': 'cookies.txt',
    'default_search': 'ytsearch',
}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

# Bot y FFmpeg opts
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

queues: dict[int, asyncio.Queue[dict]] = {}

async def enqueue_tracks(ctx, query: str):
    """Extrae tracks (playlist o single) y las encola."""
    loading = await ctx.send("⏳ Cargando pistas, por favor espera...")
    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
    tracks = []
    if not data:
        await loading.edit(content="❌ No se pudo obtener información.")
        return tracks

    def build(entry):
        return {
            'webpage_url': entry.get('webpage_url'),
            'title': entry.get('title'),
            'uploader': entry.get('uploader'),
            'duration': entry.get('duration'),
            'thumbnail': entry.get('thumbnail')
        }

    if 'entries' in data:
        for entry in data['entries'] or []:
            if entry and entry.get('webpage_url'):
                tracks.append(build(entry))
    else:
        tracks.append(build(data))

    q = queues.setdefault(ctx.guild.id, asyncio.Queue())
    for t in tracks:
        await q.put(t)

    await loading.edit(content=f"✅ Encoladas **{len(tracks)}** pista(s).")
    return tracks

async def play_next(ctx):
    """Toma la siguiente pista de la cola, extrae formats + headers y la reproduce."""
    q = queues.get(ctx.guild.id)
    vc = ctx.guild.voice_client
    if not q or q.empty():
        if vc: await vc.disconnect()
        return

    track = await q.get()
    # extrae info completa
    info = await bot.loop.run_in_executor(None,
        lambda: ytdl.extract_info(track['webpage_url'], download=False)
    )
    if not info or 'formats' not in info:
        return await play_next(ctx)

    # elegir el mejor format de audio
    fmt = max(info['formats'], key=lambda f: f.get('abr', 0))  # o filtrar mime audio
    url = fmt['url']
    headers = fmt.get('http_headers', {})
    # construir -headers string
    hdr_str = "".join(f"{k}: {v}\\r\\n" for k,v in headers.items())

    # FFmpeg con reconnect y headers
    before = (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        f"-headers \"{hdr_str}\""
    )
    source = discord.FFmpegPCMAudio(url, before_options=before, options='-vn')
    vc.play(source, after=lambda e: bot.loop.create_task(play_next(ctx)))

    # crear embed
    dur = track.get('duration', 0)
    m,s = divmod(dur, 60)
    embed = discord.Embed(
        title=track['title'], url=track['webpage_url'],
        color=discord.Color.green(),
        description=f"**Uploader:** {track['uploader']}\n**Duración:** {m}:{s:02d}"
    )
    if track.get('thumbnail'): embed.set_thumbnail(url=track['thumbnail'])

    # botones
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="⏯️ Pause/Resume",
                    style=discord.ButtonStyle.primary, custom_id="pause"))
    view.add_item(discord.ui.Button(label="⏭️ Skip",
                    style=discord.ButtonStyle.secondary, custom_id="skip"))
    view.add_item(discord.ui.Button(label="⏹️ Stop",
                    style=discord.ButtonStyle.danger, custom_id="stop"))

    msg = await ctx.send(embed=embed, view=view)

    async def on_int(interaction: discord.Interaction):
        if interaction.message.id != msg.id: return
        vc2 = ctx.guild.voice_client
        cid = interaction.data.get('custom_id')
        if cid == "pause":
            if vc2.is_paused(): vc2.resume()
            else: vc2.pause()
            await interaction.response.edit_message(embed=embed, view=view)
        elif cid == "skip":
            vc2.stop(); await interaction.response.send_message("⏭️ Saltado", ephemeral=True)
        elif cid == "stop":
            vc2.stop(); await vc2.disconnect()
            queues.pop(ctx.guild.id, None)
            await interaction.response.send_message("⏹️ Detenido", ephemeral=True)

    bot.add_listener(on_int, 'on_interaction')

@bot.command()
async def join(ctx):
    if not ctx.author.voice: return await ctx.send("❌ Conéctate a voz primero.")
    await ctx.author.voice.channel.connect()
    await ctx.send("✅ Unido al canal.")

@bot.command()
async def leave(ctx):
    vc = ctx.guild.voice_client
    if vc: await vc.disconnect(); queues.pop(ctx.guild.id, None); return await ctx.send("👋 Desconectado")
    await ctx.send("❌ No estoy en canal.")

@bot.command()
async def play(ctx, *, query: str):
    if not ctx.author.voice: return await ctx.send("❌ Debes estar en voz.")
    vc = ctx.guild.voice_client or await ctx.author.voice.channel.connect()
    await enqueue_tracks(ctx, query)
    if not vc.is_playing(): await play_next(ctx)

@bot.command()
async def skip(ctx):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing(): vc.stop(); return await ctx.send("⏭️ Saltado")
    await ctx.send("❌ Nada que saltar.")

@bot.command(name="queue")
async def queue_cmd(ctx):
    q = queues.get(ctx.guild.id)
    if not q or q.empty(): return await ctx.send("❌ Cola vacía.")
    lst = list(q._queue)
    await ctx.send("📃 Cola:\n" + "\n".join(f"{i+1}. {t['title']}" for i,t in enumerate(lst)))

@bot.command(name="stop")
async def stop_cmd(ctx):
    vc = ctx.guild.voice_client
    if vc: vc.stop(); await vc.disconnect(); queues.pop(ctx.guild.id, None); return await ctx.send("🛑 Detenido")
    await ctx.send("❌ No en canal.")

@bot.event
async def on_ready():
    print(f"Bot listo: {bot.user}")

if __name__ == '__main__':
    bot.run(TOKEN)
