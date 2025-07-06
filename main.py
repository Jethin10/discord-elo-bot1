import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive
import json
import os

TOKEN = os.getenv("DISCORD_TOKEN")  

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
DATA_FILE = "users.json"
queue = []
pending_reports = {}

# Load or create user data
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
        print(f"Failed to sync commands: {e}")
    print(f"Bot is ready! Logged in as {bot.user}")

# /register
@bot.tree.command(name="register", description="Link your Discord to your Showdown username")
async def register(interaction: discord.Interaction, showdown_name: str):
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id in data:
        await interaction.response.send_message("You're already registered.")
        return

    data[user_id] = {
        "discord_name": interaction.user.name,
        "showdown_name": showdown_name,
        "elo": 1000,
        "wins": 0,
        "losses": 0
    }

    save_data(data)
    await interaction.response.send_message(f"Registered as {showdown_name} with 1000 Elo!")

# /profile
@bot.tree.command(name="profile", description="Check your Elo, W/L, and Showdown username")
async def profile(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.response.send_message("You're not registered. Use `/register <showdown_name>`.")
        return

    user = data[user_id]
    await interaction.response.send_message(
        f"👤 **{interaction.user.name}**\n"
        f"🔢 Elo: **{user['elo']}**\n"
        f"⚔️ W/L: {user['wins']}W / {user['losses']}L\n"
        f"🧢 Showdown: `{user['showdown_name']}`"
    )

# /matchmake
@bot.tree.command(name="matchmake", description="Enter the matchmaking queue")
async def matchmake(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.followup.send("You're not registered. Use `/register`.")
        return

    if user_id in queue:
        await interaction.followup.send("You're already in the matchmaking queue.")
        return

    queue.append(user_id)
    await interaction.followup.send("🔍 Searching for opponents...")

    best_match = None
    smallest_diff = float("inf")
    p1 = data[user_id]

    for other_id in queue:
        if other_id == user_id:
            continue
        p2 = data[other_id]
        elo_diff = abs(p1["elo"] - p2["elo"])
        if elo_diff <= 150 and elo_diff < smallest_diff:
            best_match = other_id
            smallest_diff = elo_diff

    if best_match:
        queue.remove(user_id)
        queue.remove(best_match)
        p2 = data[best_match]
        await interaction.followup.send(
            f"🎮 **MATCH FOUND!**\n"
            f"<@{user_id}> (**{p1['showdown_name']}**, {p1['elo']} Elo)\n"
            f"vs\n"
            f"<@{best_match}> (**{p2['showdown_name']}**, {p2['elo']} Elo)\n\n"
            f"Go to https://play.pokemonshowdown.com/ and challenge each other.\n"
            f"After the match, use `/report win @opponent` or `/report lose @opponent`"
        )

# /report
@bot.tree.command(name="report", description="Report battle result (requires opponent confirmation)")
@app_commands.describe(result="win or lose", opponent="Mention your opponent")
async def report(interaction: discord.Interaction, result: str, opponent: discord.Member):
    result = result.lower()
    data = load_data()
    uid = str(interaction.user.id)
    oid = str(opponent.id)

    if uid not in data or oid not in data:
        await interaction.response.send_message("Both players must be registered.")
        return

    if result not in ["win", "lose"]:
        await interaction.response.send_message("Use `win` or `lose` only.")
        return

    if uid == oid:
        await interaction.response.send_message("You can't report against yourself.")
        return

    match_key = f"{min(uid, oid)}_{max(uid, oid)}"

    if match_key in pending_reports:
        existing = pending_reports[match_key]
        if existing["reporter"] == oid and existing["result"] == ("lose" if result == "win" else "win"):
            del pending_reports[match_key]

            player = data[uid]
            opp = data[oid]
            K = 32
            expected = 1 / (1 + 10 ** ((opp["elo"] - player["elo"]) / 400))

            if result == "win":
                delta = round(K * (1 - expected))
                player["elo"] += delta
                opp["elo"] -= delta
                player["wins"] += 1
                opp["losses"] += 1
            else:
                delta = round(K * expected)
                player["elo"] -= delta
                opp["elo"] += delta
                player["losses"] += 1
                opp["wins"] += 1

            save_data(data)
            await interaction.response.send_message("✅ Result confirmed. Elo updated.")
        else:
            await interaction.response.send_message("❌ Conflict! Both players reported differently.")
    else:
        pending_reports[match_key] = {
            "reporter": uid,
            "opponent": oid,
            "result": result
        }
        await interaction.response.send_message(
            f"📋 Report submitted. Waiting for {opponent.mention} to confirm.\n"
            f"Use `/report {'lose' if result == 'win' else 'win'} @{interaction.user.name}`"
        )

# /leaderboard
@bot.tree.command(name="leaderboard", description="Top 10 players by Elo")
async def leaderboard(interaction: discord.Interaction):
    data = load_data()
    sorted_data = sorted(data.items(), key=lambda x: x[1]["elo"], reverse=True)
    msg = "**🏆 Leaderboard:**\n"
    for i, (uid, user) in enumerate(sorted_data[:10], 1):
        msg += f"{i}. {user['discord_name']} - {user['elo']} Elo\n"
    await interaction.response.send_message(msg)

# /cancelmatch
@bot.tree.command(name="cancelmatch", description="Leave matchmaking queue")
async def cancelmatch(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    if uid in queue:
        queue.remove(uid)
        await interaction.response.send_message("❌ You left the queue.")
    else:
        await interaction.response.send_message("You're not in the queue.")

# /queue_status
@bot.tree.command(name="queue_status", description="See who's in the queue")
async def queue_status(interaction: discord.Interaction):
    if not queue:
        await interaction.response.send_message("Queue is empty.")
        return
    data = load_data()
    msg = "**🕒 Queue:**\n"
    for uid in queue:
        user = data.get(uid, {"discord_name": "Unknown", "elo": "N/A"})
        msg += f"- {user['discord_name']} ({user['elo']} Elo)\n"
    await interaction.response.send_message(msg)

# /help_commands
@bot.tree.command(name="help_commands", description="List all bot commands")
async def help_commands(interaction: discord.Interaction):
    msg = """📘 **Bot Commands:**

**Setup**
- `/register <ps_username>` — Register your Showdown name
- `/profile` — View your stats
- `/cancel_register` — Delete your data

**Matchmaking**
- `/matchmake` — Join queue
- `/cancelmatch` — Leave queue
- `/queue_status` — View queue

**Battle**
- `/report win @opponent` — Report win
- `/report lose @opponent` — Report loss
- `/leaderboard` — View top 10
"""
    await interaction.response.send_message(msg)

# Run bot
keep_alive()
bot.run(TOKEN)
