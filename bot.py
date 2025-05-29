import os
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
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
    'cookies': 'cookies.txt',  # Asegúrate de colocar cookies.txt
    'default_search': 'ytsearch'
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

class MusicControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("No estoy en voz", ephemeral=True)
        if vc.is_paused():
            vc.resume()
            await interaction.response.edit_message(content="▶️ Reanudado", view=self)
        else:
            vc.pause()
            await interaction.response.edit_message(content="⏸️ Pausado", view=self)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏭️ Saltado", ephemeral=True)
        else:
            await interaction.response.send_message("Nada que saltar", ephemeral=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
            queues.pop(interaction.guild.id, None)
            await interaction.response.send_message("⏹️ Detenido y desconectado", ephemeral=True)
        else:
            await interaction.response.send_message("No estoy en canal", ephemeral=True)

async def enqueue_tracks(ctx: commands.Context, query: str):
    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
    tracks = []
    if 'entries' in data:
        for entry in data['entries']:
            vid = entry.get('id')
            url = f"https://www.youtube.com/watch?v={vid}"
            tracks.append({'url': url, 'title': entry.get('title', vid)})
    else:
        tracks.append({'url': data['url'], 'title': data.get('title')})

    q = queues.setdefault(ctx.guild.id, asyncio.Queue())
    for t in tracks:
        await q.put(t)
    return tracks

async def play_next(ctx: commands.Context):
    q = queues.get(ctx.guild.id)
    vc = ctx.guild.voice_client
    if not q or q.empty():
        if vc:
            await vc.disconnect()
        return

    track = await q.get()
    # Extraer info detallada para thumbnail
    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(track['url'], download=False))
    source = discord.FFmpegPCMAudio(data['url'], **FFMPEG_OPTS)

    embed = discord.Embed(title=data.get('title'), url=track['url'], color=discord.Color.blurple())
    thumb = data.get('thumbnail')
    if thumb:
        embed.set_thumbnail(url=thumb)

    view = MusicControls()
    vc.play(source, after=lambda e: bot.loop.create_task(play_next(ctx)))
    await ctx.send(embed=embed, view=view)

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
        await ctx.send("👋 Desconectado y cola limpiada.")
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
    items = list(q._queue)
    msg = "\n".join(f"{i+1}. {t['title']}" for i, t in enumerate(items))
    await ctx.send(f"📃 Próximas canciones:\n{msg}")

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
    bot.run(token)