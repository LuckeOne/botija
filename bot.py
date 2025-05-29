import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# Carga de variables de entorno
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configuración de yt-dlp (búsqueda y cookies)
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'cookies': 'cookies.txt',
    'default_search': 'ytsearch',
}
FFMPEG_OPTS = {'options': '-vn'}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

# Inicialización del bot
token = TOKEN
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Cola de pistas por servidor
queues: dict[int, asyncio.Queue[dict]] = {}

async def enqueue_tracks(ctx: commands.Context, query: str) -> list[dict]:
    """Extrae pistas de URL o búsqueda, maneja playlists y omite videos no disponibles."""
    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
    tracks = []
    # Función interna para procesar cada entrada
    def make_track(entry):
        return {
            'url': entry.get('webpage_url'),
            'title': entry.get('title'),
            'uploader': entry.get('uploader'),
            'duration': entry.get('duration'),  # segundos
            'thumbnail': entry.get('thumbnail')
        }

    if 'entries' in data:
        for entry in data['entries']:
            try:
                # entry puede ser dict con suficiente metadata
                track = make_track(entry)
                if track['url']:
                    tracks.append(track)
            except Exception:
                continue  # omitir entrada inválida
    else:
        tracks.append(make_track(data))

    # Encolar
    q = queues.setdefault(ctx.guild.id, asyncio.Queue())
    for t in tracks:
        await q.put(t)
    return tracks

async def play_next(ctx: commands.Context):
    """Reproduce la siguiente pista en la cola, o desconecta si no hay más."""
    q = queues.get(ctx.guild.id)
    vc = ctx.guild.voice_client
    if not q or q.empty():
        if vc:
            await vc.disconnect()
        return

    track = await q.get()
    try:
        # Extraer datos completos
        data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(track['url'], download=False))
    except Exception as e:
        # Si falla, pasar al siguiente
        return await play_next(ctx)

    source = discord.FFmpegPCMAudio(data['url'], **FFMPEG_OPTS)

    # Formatear duración mm:ss
    dur = data.get('duration') or 0
    mins, secs = divmod(dur, 60)
    duration_str = f"{mins}:{secs:02d}"

    embed = discord.Embed(
        title=data.get('title'),
        url=track['url'],
        color=discord.Color.blurple(),
        description=f"Uploader: **{data.get('uploader')}**\nDuration: **{duration_str}**"
    )
    thumb = data.get('thumbnail')
    if thumb:
        embed.set_thumbnail(url=thumb)

    # Botones de control
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary, custom_id="pause"))
    view.add_item(discord.ui.Button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, custom_id="skip"))
    view.add_item(discord.ui.Button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="stop"))

    def after_play(error):
        bot.loop.create_task(play_next(ctx))

    vc.play(source, after=after_play)
    msg = await ctx.send(embed=embed, view=view)

    # Manejar interacciones de botones
    async def on_button(interaction: discord.Interaction):
        if interaction.message.id != msg.id:
            return
        vc = ctx.guild.voice_client
        custom_id = interaction.data.get('custom_id')
        if custom_id == 'pause':
            if vc.is_paused(): vc.resume(); await interaction.response.edit_message(embed=embed, view=view)
            else: vc.pause(); await interaction.response.edit_message(embed=embed, view=view)
        elif custom_id == 'skip':
            vc.stop(); await interaction.response.send_message("⏭️ Saltado", ephemeral=True)
        elif custom_id == 'stop':
            vc.stop(); await vc.disconnect(); queues.pop(ctx.guild.id, None); await interaction.response.send_message("⏹️ Detenido", ephemeral=True)
    bot.add_listener(on_button, 'on_interaction')

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
    await ctx.send(f"📜 Encoladas {len(tracks)} pista(s): {', '.join(t['title'] for t in tracks[:3])}...")
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
    q = queues.get(ctx.guild.id)
    if not q or q.empty():
        return await ctx.send("❌ La cola está vacía.")
    titles = [t['title'] for t in list(q._queue)]
    msg = "\n".join(f"{i+1}. {title}" for i,title in enumerate(titles))
    await ctx.send(f"📃 Próximas canciones:\n{msg}")

@bot.command(name="stop")
async def stop_cmd(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc:
        vc.stop(); await vc.disconnect(); queues.pop(ctx.guild.id, None)
        await ctx.send("🛑 Detenido y desconectado.")
    else:
        await ctx.send("❌ No estoy en un canal.")

@bot.event
async def on_ready():
    print(f"Bot listo: {bot.user}")

if __name__ == '__main__':
    bot.run(token)
