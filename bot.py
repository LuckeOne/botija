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

# Cola de pistas por guild
queues: dict[int, asyncio.Queue[dict]] = {}

async def enqueue_tracks(ctx: commands.Context, query: str) -> list[dict]:
    """Extrae pistas de URL o búsqueda, maneja playlists, omite las no disponibles."""
    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
    tracks = []
    if not data:
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
            if not entry or not entry.get('webpage_url'):
                continue
            tracks.append(build(entry))
    else:
        tracks.append(build(data))

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

    # Extraer info de streaming real
    info = await bot.loop.run_in_executor(None,
        lambda: ytdl.extract_info(track['webpage_url'], download=False)
    )
    if not info or not info.get('url'):
        # Si falla, continuar con siguiente
        return await play_next(ctx)

    source = discord.FFmpegPCMAudio(info['url'], **FFMPEG_OPTS)
    vc.play(source, after=lambda e: bot.loop.create_task(play_next(ctx)))

    # Formatear duración
    dur = track.get('duration') or 0
    mins, secs = divmod(dur, 60)
    duration_str = f"{mins}:{secs:02d}"

    embed = discord.Embed(
        title=track['title'],
        url=track['webpage_url'],
        color=discord.Color.green(),
        description=f"**Uploader:** {track['uploader']}\n**Duración:** {duration_str}"
    )
    if track.get('thumbnail'):
        embed.set_thumbnail(url=track['thumbnail'])

    # Botones
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary, custom_id="pause"))
    view.add_item(discord.ui.Button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, custom_id="skip"))
    view.add_item(discord.ui.Button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="stop"))

    msg = await ctx.send(embed=embed, view=view)

    async def on_interaction(interaction: discord.Interaction):
        if interaction.message.id != msg.id:
            return
        vc = ctx.guild.voice_client
        cid = interaction.data.get('custom_id')
        if cid == "pause":
            if vc.is_paused():
                vc.resume()
            else:
                vc.pause()
            await interaction.response.edit_message(embed=embed, view=view)
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
