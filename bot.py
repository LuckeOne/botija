import os
import discord
from discord.ext import commands
import wavelink
from dotenv import load_dotenv
from urllib.parse import urlparse

# Carga variables de .env (en Railway no se usa .env, sino Variables del proyecto)
load_dotenv()

# Lectura de variables de entorno
TOKEN = os.getenv("DISCORD_TOKEN")
LAVALINK_URL = os.getenv("LAVALINK_URL")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")

# Parsear host/puerto de la URL de Lavalink
parsed = urlparse(LAVALINK_URL or "")
HOST = parsed.hostname or "localhost"
PORT = parsed.port or 2333
SECURE = (parsed.scheme == "https")

# Configuración de intents y bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    # Conectar el nodo Lavalink
    await wavelink.NodePool.connect(
        bot=bot,
        host=HOST,
        port=PORT,
        password=LAVALINK_PASSWORD,
        secure=SECURE
    )
    print(f"Lavalink conectado en {HOST}:{PORT} (secure={SECURE})")

@bot.command()
async def join(ctx):
    """Hace que el bot se una al canal de voz del autor."""
    if not ctx.author.voice:
        return await ctx.send("❌ Conéctate a un canal de voz primero.")
    await ctx.author.voice.channel.connect(cls=wavelink.Player)
    await ctx.send("✅ Me he unido al canal de voz.")

@bot.command()
async def play(ctx, *, query: str = None):
    """Reproduce una canción o playlist de YouTube."""
    if query is None:
        return await ctx.send("❌ Debes indicar nombre o enlace de YouTube.")
    # Conectar si no está en voz
    if not ctx.voice_client:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect(cls=wavelink.Player)
        else:
            return await ctx.send("❌ No estás en un canal de voz.")

    player: wavelink.Player = ctx.voice_client

    # Buscar tracks (video o playlist)
    tracks = await wavelink.YouTubeTrack.search(query, return_first=False)
    if not tracks:
        return await ctx.send("❌ No encontré resultados en YouTube.")

    # Si es playlist, encolar todo
    if "playlist" in query and len(tracks) > 1:
        await ctx.send(f"📜 Encolando playlist ({len(tracks)} canciones)...")
        for t in tracks:
            await player.queue.put_wait(t)
    else:
        track = tracks[0]
        await player.queue.put_wait(track)
        await ctx.send(f"▶️ Encolada: **{track.title}**")

    # Si no está sonando, reproduce el primero de la cola
    if not player.is_playing():
        next_track = await player.queue.get_wait()
        await player.play(next_track)

@bot.command()
async def skip(ctx):
    """Salta la canción actual."""
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        return await ctx.send("❌ No hay ninguna canción reproduciéndose.")
    await ctx.voice_client.stop()
    await ctx.send("⏭️ Canción saltada.")

@bot.command()
async def stop(ctx):
    """Detiene la reproducción y desconecta al bot."""
    if not ctx.voice_client:
        return await ctx.send("❌ No estoy en un canal de voz.")
    await ctx.voice_client.disconnect()
    await ctx.send("👋 Me he desconectado del canal de voz.")

# Ejecutar el bot
if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: La variable DISCORD_TOKEN no está definida.")
        exit(1)
    bot.run(TOKEN)
