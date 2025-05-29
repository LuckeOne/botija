import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# Carga de variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# yt-dlp + ffmpeg
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'skip_download': True,
    'cookies': 'cookies.txt',
    'default_search': 'ytsearch',
}
FFMPEG_OPTS = {
    'options': '-vn'
}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

class MusicPlayer:
    """Gestiona la cola y la reproducción en un guild."""
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self.ctx = ctx
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.play_next_song = asyncio.Event()
        self.current = None
        self.audio_task = bot.loop.create_task(self.audio_loop())

    async def audio_loop(self):
        await self.bot.wait_until_ready()
        while True:
            self.play_next_song.clear()
            url = await self.queue.get()
            # extraer info
            data = await self.bot.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
            if 'entries' in data:
                # playlist: encolar todas las entradas
                for entry in data['entries']:
                    self.queue.put_nowait(entry['url'])
                continue
            source = discord.FFmpegPCMAudio(data['url'], **FFMPEG_OPTS)
            self.current = data.get('title', url)
            vc: discord.VoiceClient = self.ctx.voice_client
            if not vc or not vc.is_connected():
                vc = await self.ctx.author.voice.channel.connect()
            vc.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next_song.set))
            await self.ctx.send(f"▶️ Reproduciendo: **{self.current}**")
            await self.play_next_song.wait()

    def add_to_queue(self, url: str):
        self.queue.put_nowait(url)

    def skip(self):
        vc = self.ctx.voice_client
        if vc and vc.is_playing():
            vc.stop()

    async def stop(self):
        vc = self.ctx.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
        self.audio_task.cancel()

class Music(commands.Cog):
    """Cog de música con comandos !join, !play, !skip, !stop, !queue."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, MusicPlayer] = {}

    def get_player(self, ctx: commands.Context) -> MusicPlayer:
        guild_id = ctx.guild.id
        if guild_id not in self.players:
            self.players[guild_id] = MusicPlayer(self.bot, ctx)
        return self.players[guild_id]

    @commands.command(name="join")
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice:
            return await ctx.send("❌ Conéctate a un canal de voz primero.")
        await ctx.author.voice.channel.connect()
        await ctx.send("✅ Me he unido al canal de voz.")

    @commands.command(name="leave")
    async def leave(self, ctx: commands.Context):
        player = self.players.pop(ctx.guild.id, None)
        if player:
            await player.stop()
            await ctx.send("👋 Me he desconectado y limpié la cola.")
        else:
            await ctx.send("❌ No estoy en un canal de voz.")

    @commands.command(name="play")
    async def play(self, ctx: commands.Context, *, query: str):
        """Encola una URL o busca en YouTube."""
        if not ctx.author.voice:
            return await ctx.send("❌ Debes estar en un canal de voz.")
        player = self.get_player(ctx)
        player.add_to_queue(query)
        await ctx.send(f"▶️ Encolado: **{query}**")

    @commands.command(name="skip")
    async def skip(self, ctx: commands.Context):
        player = self.players.get(ctx.guild.id)
        if not player:
            return await ctx.send("❌ No hay nada reproduciéndose.")
        player.skip()
        await ctx.send("⏭️ Saltando canción.")

    @commands.command(name="stop")
    async def stop(self, ctx: commands.Context):
        player = self.players.pop(ctx.guild.id, None)
        if not player:
            return await ctx.send("❌ No estoy en un canal de voz.")
        await player.stop()
        await ctx.send("🛑 Detenido y desconectado.")

    @commands.command(name="queue")
    async def queue_(self, ctx: commands.Context):
        player = self.players.get(ctx.guild.id)
        if not player or player.queue.empty():
            return await ctx.send("❌ La cola está vacía.")
        upcoming = list(player.queue._queue)
        msg = "\n".join(f"{i+1}. {item}" for i, item in enumerate(upcoming))
        await ctx.send(f"📃 Próximas canciones:\n{msg}")

# Configuración del bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

bot.add_cog(Music(bot))

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")

if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: Falta DISCORD_TOKEN")
        exit(1)
    bot.run(TOKEN)
