import discord
from discord import app_commands
from discord.ext import commands
import os
import json
from keep_alive import keep_alive  # Ensure keep_alive.py is in your repo

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
DATA_FILE = "users.json"
queue = []
pending_reports = {}

# Load/save user data
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({}, f)
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

@bot.event
async def on_ready():
    await bot.wait_until_ready()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Command sync failed: {e}")
    print(f"Bot is online: {bot.user}")

# /register
@bot.tree.command(name="register", description="Link your Discord to your Pokémon Showdown account")
async def register(interaction: discord.Interaction, showdown_name: str):
    await interaction.response.defer()
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id in data:
        await interaction.followup.send("❌ You're already registered.")
        return

    data[user_id] = {
        "discord_name": interaction.user.name,
        "showdown_name": showdown_name,
        "elo": 1000,
        "wins": 0,
        "losses": 0
    }
    save_data(data)
    await interaction.followup.send(f"✅ Registered as `{showdown_name}` with 1000 Elo.")

# /profile
@bot.tree.command(name="profile", description="View your Elo, W/L, and Showdown username")
async def profile(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.followup.send("❌ You're not registered. Use `/register <showdown_name>` first.")
        return

    user = data[user_id]
    await interaction.followup.send(
        f"👤 **{interaction.user.name}**\n"
        f"📛 Showdown: `{user['showdown_name']}`\n"
        f"🏆 Elo: **{user['elo']}**\n"
        f"📊 W/L: {user['wins']}W / {user['losses']}L"
    )

# /matchmake
@bot.tree.command(name="matchmake", description="Join the matchmaking queue")
async def matchmake(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.followup.send("❌ You must register first with `/register`.")
        return

    if user_id in queue:
        await interaction.followup.send("❌ You're already in the queue!")
        return

    queue.append(user_id)
    await interaction.followup.send("⏳ Searching for an opponent with similar Elo...")

    # Matchmaking logic
    best_match = None
    smallest_diff = float("inf")
    p1 = data[user_id]

    for other_id in queue:
        if other_id == user_id:
            continue
        p2 = data[other_id]
        diff = abs(p1["elo"] - p2["elo"])
        if diff <= 150 and diff < smallest_diff:
            best_match = other_id
            smallest_diff = diff

    if best_match:
        queue.remove(user_id)
        queue.remove(best_match)
        p2 = data[best_match]

        await interaction.followup.send(
            f"🎮 **MATCH FOUND!**\n"
            f"🔹 <@{user_id}> ({p1['showdown_name']}, {p1['elo']} Elo)\n"
            f"🔸 <@{best_match}> ({p2['showdown_name']}, {p2['elo']} Elo)\n\n"
            f"Go to https://play.pokemonshowdown.com/ and challenge each other.\n"
            f"After playing, use `/report win @opponent` or `/report lose @opponent`."
        )

# /cancel_register
@bot.tree.command(name="cancel_register", description="Delete your account and all data")
async def cancel_register(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.followup.send("❌ You're not registered.")
        return

    # Remove from queue
    if user_id in queue:
        queue.remove(user_id)

    # Remove pending reports
    to_remove = []
    for key, report in pending_reports.items():
        if report["reporter"] == user_id or report["opponent"] == user_id:
            to_remove.append(key)
    for key in to_remove:
        del pending_reports[key]

    del data[user_id]
    save_data(data)
    await interaction.followup.send("🗑️ Your account and data have been deleted.")

# Add any additional commands here (like /report, /leaderboard...)

# =================
# Run the bot
# =================
keep_alive()  # Keeps bot alive on Render
bot.run(TOKEN)
