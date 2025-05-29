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

# Opciones de yt-dlp para extracción de audio y búsqueda
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'cookies': 'cookies.txt',  # Asegúrate de tener este archivo
    'default_search': 'ytsearch',
    'extract_flat': 'in_playlist'
}
FFMPEG_OPTS = {'options': '-vn'}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

# Intents y bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Cola de pistas por guild
queues: dict[int, asyncio.Queue] = {}

class MusicControls(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx

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

async def extract_tracks(query: str):
    """Extrae información de URL o búsqueda, maneja playlists."""
    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
    tracks = []
    if 'entries' in data:
        for entry in data['entries']:
            vid = entry.get('id')
            url = f'https://www.youtube.com/watch?v={vid}'
            tracks.append({
                'url': url,
                'title': entry.get('title', vid),
                'thumbnail': entry.get('thumbnail')
            })
    else:
        tracks.append({
            'url': data['url'],
            'title': data.get('title'),
            'thumbnail': data.get('thumbnail')
        })
    return tracks

async def play_next(ctx: commands.Context):
    guild_id = ctx.guild.id
    queue = queues.get(guild_id)
    if not queue or queue.empty():
        await ctx.voice_client.disconnect()
        return

    track = await queue.get()
    vc = ctx.voice_client
    source = discord.FFmpegPCMAudio(track['url'], **FFMPEG_OPTS)

    embed = discord.Embed(title=track['title'], description=track['url'], color=discord.Color.blurple())
    if track.get('thumbnail'):
        embed.set_thumbnail(url=track['thumbnail'])
    view = MusicControls(ctx)

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
    guild_id = ctx.guild.id
    if guild_id not in queues:
        queues[guild_id] = asyncio.Queue()
    tracks = await extract_tracks(query)
    for t in tracks:
        await queues[guild_id].put(t)
    await ctx.send(f"📜 Encoladas {len(tracks)} pista(s).")

    vc = ctx.guild.voice_client or await ctx.author.voice.channel.connect()
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
    queue = queues.get(ctx.guild.id)
    if not queue or queue.empty():
        return await ctx.send("❌ Cola vacía.")
    items = list(queue._queue)
    msg = "\n".join(f"{i+1}. {t['title']}" for i,t in enumerate(items))
    await ctx.send(f"📃 Próximas:\n{msg}")

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
