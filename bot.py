import os
import discord
from discord.ext import commands
import wavelink
from dotenv import load_dotenv
from urllib.parse import urlparse

# Carga de variables de entorno
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
LAVALINK_URL = os.getenv("LAVALINK_URL")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")

# Parseo de host/puerto para la llamada a connect/create_node
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

    # Si existe NodePool.connect (Wavelink 3.x+), úsala:
    if hasattr(wavelink.NodePool, "connect"):
        try:
            await wavelink.NodePool.connect(
                bot=bot,
                host=HOST,
                port=PORT,
                password=LAVALINK_PASSWORD,
                secure=SECURE
            )
            print(f"[WAVELINK] Conectado con NodePool.connect en {HOST}:{PORT}")
            return
        except Exception as e:
            print(f"❌ Error en NodePool.connect: {e}")

    # Si existe create_node (Wavelink 2.x), úsala:
    if hasattr(wavelink.NodePool, "create_node"):
        try:
            await wavelink.NodePool.create_node(
                bot=bot,
                host=HOST,
                port=PORT,
                password=LAVALINK_PASSWORD,
                secure=SECURE
            )
            print(f"[WAVELINK] Conectado con create_node en {HOST}:{PORT}")
            return
        except Exception as e:
            print(f"❌ Error en create_node: {e}")

    # Si llegamos aquí, no se pudo conectar
    print("❌ No se pudo conectar a Lavalink: métodos connect/create_node no disponibles o fallaron.")

@bot.command()
async def join(ctx):
    if not ctx.author.voice:
        return await ctx.send("❌ Conéctate a un canal de voz primero.")
    await ctx.author.voice.channel.connect(cls=wavelink.Player)
    await ctx.send("✅ Me he unido al canal de voz.")

@bot.command()
async def play(ctx, *, query: str = None):
    if query is None:
        return await ctx.send("❌ Debes indicar nombre o enlace de YouTube.")
    if not ctx.voice_client:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect(cls=wavelink.Player)
        else:
            return await ctx.send("❌ No estás en un canal de voz.")

    player: wavelink.Player = ctx.voice_client
    tracks = await wavelink.YouTubeTrack.search(query, return_first=False)
    if not tracks:
        return await ctx.send("❌ No encontré resultados en YouTube.")

    if "playlist" in query and len(tracks) > 1:
        await ctx.send(f"📜 Encolando playlist ({len(tracks)} canciones)...")
        for t in tracks:
            await player.queue.put_wait(t)
    else:
        track = tracks[0]
        await player.queue.put_wait(track)
        await ctx.send(f"▶️ Encolada: **{track.title}**")

    if not player.is_playing():
        next_track = await player.queue.get_wait()
        await player.play(next_track)

@bot.command()
async def skip(ctx):
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        return await ctx.send("❌ No hay ninguna canción reproduciéndose.")
    await ctx.voice_client.stop()
    await ctx.send("⏭️ Canción saltada.")

@bot.command()
async def stop(ctx):
    if not ctx.voice_client:
        return await ctx.send("❌ No estoy en un canal de voz.")
    await ctx.voice_client.disconnect()
    await ctx.send("👋 Me he desconectado del canal de voz.")

if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: La variable DISCORD_TOKEN no está definida.")
        exit(1)
    bot.run(TOKEN)
