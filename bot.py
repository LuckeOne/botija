import os
import discord
from discord.ext import commands
import wavelink
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
print("TOKEN:", TOKEN)
LAVALINK_URL = os.getenv("LAVALINK_URL")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    await wavelink.NodePool.create_node(
        bot=bot,
        uri=LAVALINK_URL,
        password=LAVALINK_PASSWORD,
        secure=False
    )

@bot.command()
async def join(ctx):
    if not ctx.author.voice:
        return await ctx.send("Conéctate a un canal de voz primero.")
    await ctx.author.voice.channel.connect(cls=wavelink.Player)

@bot.command()
async def play(ctx, *, query: str):
    if not ctx.voice_client:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect(cls=wavelink.Player)
        else:
            return await ctx.send("No estás en un canal de voz.")

    player: wavelink.Player = ctx.voice_client

    # Si es un enlace de playlist o video
    tracks = await wavelink.YouTubeTrack.search(query, return_first=False)

    if not tracks:
        return await ctx.send("No encontré resultados.")

    if "playlist" in query:
        await ctx.send(f"Añadiendo {len(tracks)} canciones de la playlist...")
        for track in tracks:
            await player.queue.put_wait(track)
    else:
        await player.queue.put_wait(tracks[0])
        await ctx.send(f"Agregada: **{tracks[0].title}**")

    if not player.is_playing():
        await player.play(await player.queue.get_wait())

@bot.command()
async def skip(ctx):
    if not ctx.voice_client:
        return await ctx.send("No estoy reproduciendo nada.")
    await ctx.voice_client.stop()
    await ctx.send("⏭️ Saltando canción...")

@bot.command()
async def stop(ctx):
    if not ctx.voice_client:
        return await ctx.send("No estoy en un canal.")
    await ctx.voice_client.disconnect()
    await ctx.send("👋 Me salí del canal.")

bot.run(TOKEN)
