import os
import discord
from discord.ext import commands
import wavelink
from dotenv import load_dotenv
from urllib.parse import urlparse

# Carga las variables de entorno
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
LAVALINK_URL = os.getenv("LAVALINK_URL")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")

# Parseo de host/puerto para NodePool
parsed = urlparse(LAVALINK_URL or "")
HOST = parsed.hostname or "localhost"
PORT = parsed.port or 2333
SECURE = (parsed.scheme == "https")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")

    # 1) Intentamos create_node (Wavelink 2.x / 2.6.x)
    if hasattr(wavelink.NodePool, "create_node"):
        try:
            await wavelink.NodePool.create_node(
                bot=bot,
                host=HOST,
                port=PORT,
                password=LAVALINK_PASSWORD,
                secure=SECURE
            )
            print(f"[WAVELINK] Usando NodePool.create_node, nodos: {wavelink.NodePool._nodes}")
        except Exception as e:
            print(f"❌ Error en create_node: {e}")

    # 2) Si no funcionó, intentamos connect (Wavelink 3.x+)
    elif hasattr(wavelink.NodePool, "connect"):
        try:
            await wavelink.NodePool.connect(
                bot=bot,
                host=HOST,
                port=PORT,
                password=LAVALINK_PASSWORD,
                secure=SECURE
            )
            print(f"[WAVELINK] Usando NodePool.connect, nodos: {wavelink.NodePool._nodes}")
        except Exception as e:
            print(f"❌ Error en NodePool.connect: {e}")

    # 3) Verificamos cuántos nodos efectivamente conectados
    nodes = getattr(wavelink.NodePool, "_nodes", None)
    count = len(nodes) if nodes else 0
    print(f"[WAVELINK] Nodos activos tras on_ready: {count}")

@bot.command()
async def join(ctx):
    # Depuración: antes de unirnos, mostramos lista de nodos conectados
    nodes = getattr(wavelink.NodePool, "_nodes", [])
    print(f"[join] Nodos disponibles: {nodes}")

    if not nodes:
        return await ctx.send("❌ No hay nodos Lavalink conectados. Revisa los logs de on_ready.")
    if not ctx.author.voice:
        return await ctx.send("❌ Conéctate a un canal de voz primero.")

    # Esto inicializa el player y asigna un nodo
    player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
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
