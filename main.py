import discord
from discord import app_commands
from discord.ext import commands
import os
import json
from keep_alive import keep_alive  # keeps bot alive on Render

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
DATA_FILE = "users.json"
queue = []
pending_reports = {}

# Load and save Elo data
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
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    print(f"Bot is ready! Logged in as {bot.user}")

# Register command
@bot.tree.command(name="register", description="Link your Discord to your Showdown username")
async def register(interaction: discord.Interaction, showdown_name: str):
    await interaction.response.defer()
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id in data:
        await interaction.followup.send("You're already registered.")
        return

    data[user_id] = {
        "discord_name": interaction.user.name,
        "showdown_name": showdown_name,
        "elo": 1000,
        "wins": 0,
        "losses": 0
    }
    save_data(data)
    await interaction.followup.send(f"✅ Registered as `{showdown_name}` with 1000 Elo!")

# Cancel register
@bot.tree.command(name="cancel_register", description="Delete your registration and data")
async def cancel_register(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.followup.send("❌ You're not registered.")
        return

    queue[:] = [uid for uid in queue if uid != user_id]
    for key in list(pending_reports.keys()):
        if user_id in key:
            del pending_reports[key]

    del data[user_id]
    save_data(data)
    await interaction.followup.send("🗑️ Your registration and data have been deleted.")

# Profile command
@bot.tree.command(name="profile", description="Check your Elo and stats")
async def profile(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.followup.send("You’re not registered. Use `/register <ps_username>`.")
        return

    user = data[user_id]
    await interaction.followup.send(
        f"👤 **{interaction.user.name}**\n"
        f"🔢 Elo: **{user['elo']}**\n"
        f"🏆 W/L: {user['wins']}W / {user['losses']}L\n"
        f"🧢 Showdown: `{user['showdown_name']}`"
    )

# Matchmaking command
@bot.tree.command(name="matchmake", description="Join the matchmaking queue")
async def matchmake(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.followup.send("Register first using `/register`.")
        return
    if user_id in queue:
        await interaction.followup.send("You’re already in the queue.")
        return

    queue.append(user_id)
    await interaction.followup.send("🔍 Searching for opponents...")

    p1 = data[user_id]
    match = None
    best_diff = float("inf")

    for other in queue:
        if other != user_id:
            p2 = data[other]
            diff = abs(p1["elo"] - p2["elo"])
            if diff <= 150 and diff < best_diff:
                match = other
                best_diff = diff

    if match:
        queue.remove(user_id)
        queue.remove(match)
        p2 = data[match]
        await interaction.followup.send(
            f"🎮 **MATCH FOUND!**\n"
            f"<@{user_id}> (`{p1['showdown_name']}`, {p1['elo']} Elo) vs "
            f"<@{match}> (`{p2['showdown_name']}`, {p2['elo']} Elo)\n\n"
            f"Challenge each other on https://play.pokemonshowdown.com/"
        )

# Cancel match
@bot.tree.command(name="cancelmatch", description="Leave the matchmaking queue")
async def cancelmatch(interaction: discord.Interaction):
    await interaction.response.defer()
    user_id = str(interaction.user.id)
    if user_id in queue:
        queue.remove(user_id)
        await interaction.followup.send("❌ You’ve left the matchmaking queue.")
    else:
        await interaction.followup.send("You're not in the queue.")

# Queue status
@bot.tree.command(name="queue_status", description="See who is in queue")
async def queue_status(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    if not queue:
        await interaction.followup.send("🔕 The matchmaking queue is empty.")
        return
    msg = "**🎮 Current Queue:**\n"
    for uid in queue:
        user = data.get(uid)
        msg += f"- {user['discord_name']} ({user['elo']} Elo)\n"
    await interaction.followup.send(msg)

# Report result
@bot.tree.command(name="report", description="Report match result (needs opponent confirmation)")
@app_commands.describe(result="win or lose", opponent="Mention your opponent")
async def report(interaction: discord.Interaction, result: str, opponent: discord.Member):
    await interaction.response.defer()
    data = load_data()
    uid = str(interaction.user.id)
    oid = str(opponent.id)

    if uid not in data or oid not in data:
        await interaction.followup.send("Both players must be registered.")
        return

    if uid == oid or result.lower() not in ["win", "lose"]:
        await interaction.followup.send("Invalid usage. You can't report yourself.")
        return

    key = f"{min(uid, oid)}_{max(uid, oid)}"
    if key in pending_reports:
        prev = pending_reports[key]
        if prev["reporter"] == oid and prev["result"] != result:
            del pending_reports[key]
            winner = data[uid] if result == "win" else data[oid]
            loser = data[oid] if result == "win" else data[uid]
            K = 32
            expected = 1 / (1 + 10 ** ((loser["elo"] - winner["elo"]) / 400))
            delta = round(K * (1 - expected))

            winner["elo"] += delta
            winner["wins"] += 1
            loser["elo"] -= delta
            loser["losses"] += 1

            save_data(data)
            await interaction.followup.send(
                f"✅ **Match confirmed!**\n"
                f"🏆 {winner['discord_name']}: +{delta} Elo\n"
                f"💔 {loser['discord_name']}: -{delta} Elo"
            )
            return
        else:
            await interaction.followup.send("⚠️ There's already a conflicting report. Use `/cancel_report` to fix it.")
            return

    pending_reports[key] = {"reporter": uid, "opponent": oid, "result": result}
    await interaction.followup.send(
        f"📋 Report submitted: You reported a **{result}** vs <@{oid}>.\n"
        f"<@{oid}>, please confirm by using `/report {'win' if result == 'lose' else 'lose'} @{interaction.user.name}`."
    )

# Cancel report
@bot.tree.command(name="cancel_report", description="Cancel your pending report")
async def cancel_report(interaction: discord.Interaction):
    await interaction.response.defer()
    uid = str(interaction.user.id)
    for key, report in list(pending_reports.items()):
        if uid in key:
            del pending_reports[key]
            await interaction.followup.send("❌ Your pending report has been cancelled.")
            return
    await interaction.followup.send("You don’t have any pending reports.")

# Leaderboard
@bot.tree.command(name="leaderboard", description="View top 10 players by Elo")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    sorted_users = sorted(data.items(), key=lambda x: x[1]["elo"], reverse=True)
    msg = "**🏆 Leaderboard:**\n"
    for i, (uid, user) in enumerate(sorted_users[:10], 1):
        msg += f"{i}. {user['discord_name']} - {user['elo']} Elo\n"
    await interaction.followup.send(msg)

# Help command
@bot.tree.command(name="help_commands", description="List all bot commands")
async def help_commands(interaction: discord.Interaction):
    await interaction.response.send_message("""
📘 **Commands:**

**Setup**
- `/register <name>` — Register your Showdown name
- `/cancel_register` — Delete your data

**Matchmaking**
- `/matchmake`, `/cancelmatch`, `/queue_status`

**Battle**
- `/report win/lose @opponent`, `/cancel_report`

**Stats**
- `/profile`, `/leaderboard`
""")

# Run the bot
keep_alive()
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ DISCORD_TOKEN not found!")
