import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# Carga de configuración
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Opciones de yt-dlp para manejar playlists y errores
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'ignoreerrors': True,       # Ignorar videos no disponibles
    'cookies': 'cookies.txt',    # Coloca tu cookies.txt en el repo
    'default_search': 'ytsearch',
}
# Opciones de FFmpeg: reconexión y sin video
FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Cola de pistas por guild
queues: dict[int, asyncio.Queue[dict]] = {}

async def enqueue_tracks(ctx: commands.Context, query: str) -> list[dict]:
    """Extrae info de URL o búsqueda, maneja playlists y omite entradas erróneas."""
    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
    tracks = []
    def make_track(entry):
        return {
            'url': entry.get('webpage_url'),
            'title': entry.get('title'),
            'uploader': entry.get('uploader'),
            'duration': entry.get('duration'),
            'thumbnail': entry.get('thumbnail')
        }

    if not data:
        return tracks

    if 'entries' in data:
        for entry in data['entries']:
            if not entry:
                continue
            track = make_track(entry)
            if track['url']:
                tracks.append(track)
    else:
        tracks.append(make_track(data))

    q = queues.setdefault(ctx.guild.id, asyncio.Queue())
    for t in tracks:
        await q.put(t)
    return tracks

async def play_next(ctx: commands.Context):
    """Reproduce la siguiente pista o se desconecta al terminar."""
    guild_id = ctx.guild.id
    q = queues.get(guild_id)
    vc = ctx.guild.voice_client
    if not q or q.empty():
        if vc:
            await vc.disconnect()
        return

    track = await q.get()
    # Crea la fuente con reconexión
    source = discord.FFmpegPCMAudio(track['url'], **FFMPEG_OPTS)
    vc.play(source, after=lambda e: bot.loop.create_task(play_next(ctx)))

    # Formatear duración
    dur = track.get('duration') or 0
    mins, secs = divmod(dur, 60)
    duration_str = f"{mins}:{secs:02d}"

    embed = discord.Embed(
        title=track['title'],
        url=track['url'],
        color=discord.Color.green(),
        description=f"**Uploader:** {track['uploader']}\n**Duración:** {duration_str}"
    )
    if track.get('thumbnail'):
        embed.set_thumbnail(url=track['thumbnail'])

    # Botones de control
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary, custom_id="pause"))
    view.add_item(discord.ui.Button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, custom_id="skip"))
    view.add_item(discord.ui.Button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="stop"))

    msg = await ctx.send(embed=embed, view=view)

    # Manejar interacciones
    async def on_interaction(interaction: discord.Interaction):
        if interaction.message.id != msg.id:
            return
        vc = ctx.guild.voice_client
        cid = interaction.data.get('custom_id')
        if cid == "pause":
            if vc.is_paused():
                vc.resume()
                await interaction.response.edit_message(content=None, embed=embed, view=view)
            else:
                vc.pause()
                await interaction.response.edit_message(content=None, embed=embed, view=view)
        elif cid == "skip":
            if vc.is_playing():
                vc.stop()
            await interaction.response.send_message("⏭️ Saltado", ephemeral=True)
        elif cid == "stop":
            vc.stop()
            await vc.disconnect()
            queues.pop(ctx.guild.id, None)
            await interaction.response.send_message("⏹️ Detenido y desconectado", ephemeral=True)

    bot.add_listener(on_interaction, 'on_interaction')

@bot.command()
async def join(ctx: commands.Context):
    if not ctx.author.voice:
        return await ctx.send("❌ Conéctate a un canal de voz primero.")
    await ctx.author.voice.channel.connect()
    await ctx.send("✅ Unido al canal.")

@bot.command()
async def leave(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc:
        await vc.disconnect()
        queues.pop(ctx.guild.id, None)
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
        return await ctx.send("❌ No encontré pistas válidas.")
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
        await ctx.send("❌ No hay nada reproduciendo.")

@bot.command(name="queue")
async def queue_cmd(ctx: commands.Context):
    q = queues.get(ctx.guild.id)
    if not q or q.empty():
        return await ctx.send("❌ La cola está vacía.")
    items = list(q._queue)
    msg = "\n".join(f"{i+1}. {t['title']}" for i, t in enumerate(items))
    await ctx.send(f"📃 Cola:\n{msg}")

@bot.command(name="stop")
async def stop_cmd(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
        queues.pop(ctx.guild.id, None)
        await ctx.send("🛑 Detenido y desconectado.")
    else:
        await ctx.send("❌ No estoy en un canal.")

@bot.event
async def on_ready():
    print(f"Bot listo: {bot.user}")

if __name__ == '__main__':
    bot.run(TOKEN)