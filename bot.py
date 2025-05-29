import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# Carga de variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Opciones de yt-dlp
ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'ignoreerrors': True,
    'cookies': 'cookies.txt',
    'default_search': 'ytsearch',
}
ytdl = yt_dlp.YoutubeDL(ytdl_opts)

# FFmpeg opciones
tools_before = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
)
ffmpeg_opts = {
    'before_options': tools_before,
    'options': '-vn'
}

# Bot e intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Cola de pistas por servidor
queues: dict[int, asyncio.Queue[dict]] = {}

async def enqueue_tracks(ctx: commands.Context, query: str) -> list[dict]:
    loading = await ctx.send("⏳ Cargando pistas...")
    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
    tracks = []
    if not data:
        await loading.edit(content="❌ No se pudo cargar información.")
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

    await loading.edit(content=f"✅ Encoladas {len(tracks)} pista(s).")
    return tracks

async def play_next(ctx: commands.Context):
    q = queues.get(ctx.guild.id)
    vc = ctx.guild.voice_client
    if not q or q.empty():
        if vc:
            await vc.disconnect()
        return

    track = await q.get()
    # Extraer info de streaming con headers\    
    info = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(track['webpage_url'], download=False))
    if not info or 'formats' not in info:
        return await play_next(ctx)

    # Filtrar formatos con audio
    audio_formats = [f for f in info['formats'] if f.get('acodec') != 'none' and f.get('url')]
    if not audio_formats:
        return await play_next(ctx)
    # Elegir el de mayor bitrate
    best = max(audio_formats, key=lambda f: f.get('abr', 0) or 0)
    url = best['url']
    headers = best.get('http_headers', {})
    header_str = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())

    before = f"{tools_before} -headers \"{header_str}\""
    source = discord.FFmpegPCMAudio(url, before_options=before, options='-vn')
    vc.play(source, after=lambda e: bot.loop.create_task(play_next(ctx)))

    dur = track.get('duration') or 0
    m, s = divmod(dur, 60)
    duration_str = f"{m}:{s:02d}"

    embed = discord.Embed(
        title=track['title'],
        url=track['webpage_url'],
        color=discord.Color.green(),
        description=f"**Uploader:** {track['uploader']}\n**Duración:** {duration_str}"
    )
    if track.get('thumbnail'):
        embed.set_thumbnail(url=track['thumbnail'])

    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary, custom_id="pause"))
    view.add_item(discord.ui.Button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, custom_id="skip"))
    view.add_item(discord.ui.Button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="stop"))

    msg = await ctx.send(embed=embed, view=view)

    async def on_int(interaction: discord.Interaction):
        if interaction.message.id != msg.id:
            return
        vc2 = ctx.guild.voice_client
        cid = interaction.data.get('custom_id')
        if cid == 'pause':
            if vc2.is_paused(): vc2.resume()
            else: vc2.pause()
            await interaction.response.edit_message(embed=embed, view=view)
        elif cid == 'skip':
            vc2.stop(); await interaction.response.send_message('⏭️ Saltado', ephemeral=True)
        elif cid == 'stop':
            vc2.stop(); await vc2.disconnect(); queues.pop(ctx.guild.id, None)
            await interaction.response.send_message('⏹️ Detenido', ephemeral=True)
    bot.remove_listener(on_int, 'on_interaction')
    bot.add_listener(on_int, 'on_interaction')

@bot.command()
async def join(ctx: commands.Context):
    if not ctx.author.voice:
        return await ctx.send('❌ Conéctate a un canal de voz primero.')
    await ctx.author.voice.channel.connect()
    await ctx.send('✅ Unido al canal.')

@bot.command()
async def leave(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc:
        await vc.disconnect()
        queues.pop(ctx.guild.id, None)
        return await ctx.send('👋 Desconectado y cola limpia.')
    await ctx.send('❌ No estoy en un canal.')

@bot.command()
async def play(ctx: commands.Context, *, query: str):
    if not ctx.author.voice:
        return await ctx.send('❌ Debes estar en un canal de voz.')
    vc = ctx.guild.voice_client or await ctx.author.voice.channel.connect()
    await enqueue_tracks(ctx, query)
    if not vc.is_playing():
        await play_next(ctx)

@bot.command()
async def skip(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.stop(); await ctx.send('⏭️ Saltado')
    else:
        await ctx.send('❌ No hay nada que saltar.')

@bot.command(name='queue')
async def queue_cmd(ctx: commands.Context):
    q = queues.get(ctx.guild.id)
    if not q or q.empty():
        return await ctx.send('❌ La cola está vacía.')
    items = list(q._queue)
    msg = '\n'.join(f"{i+1}. {t['title']}" for i,t in enumerate(items))
    await ctx.send('📃 Cola:\n'+msg)

@bot.command(name='stop')
async def stop_cmd(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc:
        vc.stop(); await vc.disconnect(); queues.pop(ctx.guild.id, None)
        return await ctx.send('🛑 Detenido y desconectado')
    await ctx.send('❌ No estoy en un canal.')

@bot.event
async def on_ready():
    print(f"Bot listo: {bot.user}")

if __name__ == '__main__':
    bot.run(TOKEN)
