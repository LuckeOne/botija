import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# yt-dlp options
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'ignoreerrors': True,
    'cookies': 'cookies.txt',
    'default_search': 'ytsearch',
}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

# FFmpeg reconnect + no video
FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTS = {
    'before_options': FFMPEG_BEFORE,
    'options': '-vn'
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# One MusicPlayer per guild
players: dict[int, "MusicPlayer"] = {}

class MusicControls(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="⏯ Pause/Resume", style=discord.ButtonStyle.primary, custom_id="music:pause")
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("No estoy conectado.", ephemeral=True)
        if vc.is_paused():
            vc.resume()
            await interaction.response.edit_message(content="▶ Reanudado", view=self)
        else:
            vc.pause()
            await interaction.response.edit_message(content="⏸ Pausado", view=self)

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.secondary, custom_id="music:skip")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏭ Saltado", ephemeral=True)
        else:
            await interaction.response.send_message("Nada que saltar.", ephemeral=True)

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger, custom_id="music:stop")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = players.pop(self.guild_id, None)
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
        if player:
            player.task.cancel()
        await interaction.response.send_message("⏹ Detenido y desconectado.", ephemeral=True)

class MusicPlayer:
    def __init__(self, ctx: commands.Context):
        self.ctx = ctx
        self.guild_id = ctx.guild.id
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self.task = bot.loop.create_task(self.player_loop())

    async def enqueue(self, track: dict):
        await self.queue.put(track)

    async def player_loop(self):
        # Connect if not already
        if not self.ctx.guild.voice_client:
            await self.ctx.author.voice.channel.connect()
        vc = self.ctx.guild.voice_client

        while True:
            track = await self.queue.get()
            # Extract direct stream info
            info = await bot.loop.run_in_executor(
                None,
                lambda: ytdl.extract_info(track['webpage_url'], download=False)
            )
            if not info or 'formats' not in info:
                continue

            # Choose best audio format
            formats = [f for f in info['formats'] if f.get('url')]
            fmt = max(formats, key=lambda f: f.get('abr') or 0)
            url = fmt['url']
            headers = fmt.get('http_headers', {})
            hdr_str = "".join(f"{k}: {v}\r\n" for k,v in headers.items())
            before = f"{FFMPEG_BEFORE} -headers \"{hdr_str}\""
            source = discord.FFmpegPCMAudio(url, before_options=before, options='-vn')

            # Build embed
            duration = track.get('duration') or 0
            m, s = divmod(duration, 60)
            embed = discord.Embed(
                title=track['title'],
                url=track['webpage_url'],
                color=discord.Color.green(),
                description=f"**Uploader:** {track['uploader']}\n**Duración:** {m}:{s:02d}"
            )
            thumb = track.get('thumbnail')
            if thumb:
                embed.set_thumbnail(url=thumb)

            # Play and send embed with controls
            vc.play(source)
            view = MusicControls(self.guild_id)
            await self.ctx.send(embed=embed, view=view)

            # Wait until done
            while vc.is_playing() or vc.is_paused():
                await asyncio.sleep(1)

            # If queue is empty, disconnect and stop
            if self.queue.empty():
                await vc.disconnect()
                break

@bot.command()
async def play(ctx: commands.Context, *, query: str):
    """Encola y reproduce URL o búsqueda de YouTube."""
    if not ctx.author.voice:
        return await ctx.send("❌ Debes unirte a un canal de voz primero.")
    player = players.get(ctx.guild.id)
    if not player:
        player = MusicPlayer(ctx)
        players[ctx.guild.id] = player

    # Loading message
    loading = await ctx.send("⏳ Cargando pistas...")
    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
    tracks = []
    def build(entry):
        return {
            'webpage_url': entry.get('webpage_url'),
            'title': entry.get('title'),
            'uploader': entry.get('uploader'),
            'duration': entry.get('duration'),
            'thumbnail': entry.get('thumbnail')
        }

    if data and 'entries' in data:
        for e in data['entries'] or []:
            if e and e.get('webpage_url'):
                tracks.append(build(e))
    elif data:
        tracks.append(build(data))

    for t in tracks:
        await player.enqueue(t)

    await loading.edit(content=f"✅ Encoladas {len(tracks)} pista(s).")

@bot.command()
async def skip(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await ctx.send("⏭ Saltado.")
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
        player.task.cancel()
    await ctx.send("⏹ Detenido y desconectado.")

@bot.command()
async def queue(ctx: commands.Context):
    q = players.get(ctx.guild.id)
    if not q or q.queue.empty():
        return await ctx.send("❌ La cola está vacía.")
    items = list(q.queue._queue)
    msg = "\n".join(f"{i+1}. {t['title']}" for i, t in enumerate(items))
    await ctx.send(f"📃 Cola:\n{msg}")

@bot.command()
async def join(ctx: commands.Context):
    if ctx.author.voice:
        await ctx.author.voice.channel.connect()
        await ctx.send("✅ Unido al canal.")
    else:
        await ctx.send("❌ Conéctate a un canal primero.")

@bot.command()
async def leave(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc:
        await vc.disconnect()
        players.pop(ctx.guild.id, None)
        await ctx.send("👋 Desconectado y cola limpia.")
    else:
        await ctx.send("❌ No estoy en un canal.")

@bot.event
async def on_ready():
    print(f"Bot listo: {bot.user}")

if __name__ == '__main__':
    bot.run(TOKEN)
