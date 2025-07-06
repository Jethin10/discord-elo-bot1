import discord
from discord import app_commands
from discord.ext import commands
import os
import json
from keep_alive import keep_alive  # For 24/7 hosting via web ping

# Load bot token
TOKEN = os.getenv("DISCORD_TOKEN") or "your-bot-token-here"  # Replace if not using env

# Discord intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Bot instance
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Storage
DATA_FILE = "users.json"
queue = []
pending_reports = {}

# Load and save functions
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({}, f)
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# On ready sync commands
@bot.event
async def on_ready():
    await bot.wait_until_ready()
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print("Failed to sync commands:", e)
    print(f"✅ Bot is ready. Logged in as {bot.user}")

# Register
@tree.command(name="register", description="Link your Discord to your Showdown username")
async def register(interaction: discord.Interaction, showdown_name: str):
    data = load_data()
    uid = str(interaction.user.id)
    if uid in data:
        await interaction.response.send_message("❌ You're already registered.")
        return

    data[uid] = {
        "discord_name": interaction.user.name,
        "showdown_name": showdown_name,
        "elo": 1000,
        "wins": 0,
        "losses": 0
    }
    save_data(data)
    await interaction.response.send_message(f"✅ Registered as `{showdown_name}` with 1000 Elo.")

# Cancel Register
@tree.command(name="cancel_register", description="Delete your account and data")
async def cancel_register(interaction: discord.Interaction):
    data = load_data()
    uid = str(interaction.user.id)
    if uid not in data:
        await interaction.response.send_message("You're not registered.")
        return
    if uid in queue:
        queue.remove(uid)
    data.pop(uid)
    save_data(data)
    await interaction.response.send_message("🗑️ Your registration and data have been deleted.")

# Profile
@tree.command(name="profile", description="View your Elo, W/L, and username")
async def profile(interaction: discord.Interaction):
    data = load_data()
    uid = str(interaction.user.id)
    if uid not in data:
        await interaction.response.send_message("You're not registered.")
        return
    user = data[uid]
    await interaction.response.send_message(
        f"👤 **{interaction.user.name}**\n"
        f"🔢 Elo: {user['elo']}\n"
        f"⚔️ W/L: {user['wins']}W / {user['losses']}L\n"
        f"🧢 Showdown: `{user['showdown_name']}`"
    )

# Matchmake
@tree.command(name="matchmake", description="Join the matchmaking queue")
async def matchmake(interaction: discord.Interaction):
    data = load_data()
    uid = str(interaction.user.id)
    if uid not in data:
        await interaction.response.send_message("Register first using `/register`.")
        return
    if uid in queue:
        await interaction.response.send_message("You're already in the queue.")
        return

    queue.append(uid)
    await interaction.response.defer(thinking=True)
    await interaction.followup.send("🔍 Searching for a match...")

    best_match = None
    p1 = data[uid]
    smallest_diff = float("inf")

    for other_id in queue:
        if other_id == uid:
            continue
        p2 = data[other_id]
        diff = abs(p1["elo"] - p2["elo"])
        if diff <= 150 and diff < smallest_diff:
            best_match = other_id
            smallest_diff = diff

    if best_match:
        queue.remove(uid)
        queue.remove(best_match)
        p2 = data[best_match]
        await interaction.followup.send(
            f"🎮 **MATCH FOUND!**\n"
            f"<@{uid}> (`{p1['showdown_name']}` | {p1['elo']} Elo)\n"
            f"vs\n"
            f"<@{best_match}> (`{p2['showdown_name']}` | {p2['elo']} Elo)\n\n"
            f"Battle at https://play.pokemonshowdown.com/\n"
            f"Report after the match with `/report win @user` or `/report lose @user`"
        )

# Cancel Match
@tree.command(name="cancelmatch", description="Leave the matchmaking queue")
async def cancelmatch(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    if uid in queue:
        queue.remove(uid)
        await interaction.response.send_message("❌ You left the queue.")
    else:
        await interaction.response.send_message("You're not in the queue.")

# Queue Status
@tree.command(name="queue_status", description="See who is in queue")
async def queue_status(interaction: discord.Interaction):
    if not queue:
        await interaction.response.send_message("📭 Queue is empty.")
        return
    data = load_data()
    msg = "**🔁 Current Queue:**\n"
    for uid in queue:
        u = data.get(uid)
        if u:
            msg += f"- {u['discord_name']} ({u['elo']} Elo)\n"
    await interaction.response.send_message(msg)

# Report
@tree.command(name="report", description="Report match result (needs opponent to confirm)")
@app_commands.describe(result="Choose win or lose", opponent="Mention your opponent")
async def report(interaction: discord.Interaction, result: str, opponent: discord.Member):
    result = result.lower()
    uid = str(interaction.user.id)
    oid = str(opponent.id)
    data = load_data()

    if uid not in data or oid not in data:
        await interaction.response.send_message("Both players must be registered.")
        return
    if result not in ["win", "lose"]:
        await interaction.response.send_message("Result must be `win` or `lose`.")
        return
    if uid == oid:
        await interaction.response.send_message("You can't report a match against yourself.")
        return

    key = f"{min(uid, oid)}_{max(uid, oid)}"
    if key in pending_reports:
        other = pending_reports[key]
        if other["reporter"] == oid and other["result"] == ("lose" if result == "win" else "win"):
            del pending_reports[key]
            K = 32
            player = data[uid]
            enemy = data[oid]
            expected = 1 / (1 + 10 ** ((enemy["elo"] - player["elo"]) / 400))

            if result == "win":
                delta = round(K * (1 - expected))
                player["elo"] += delta
                enemy["elo"] -= delta
                player["wins"] += 1
                enemy["losses"] += 1
            else:
                delta = round(K * expected)
                player["elo"] -= delta
                enemy["elo"] += delta
                player["losses"] += 1
                enemy["wins"] += 1

            save_data(data)
            await interaction.response.send_message(
                f"✅ Result confirmed! Elo updated.\n"
                f"🏆 {player['discord_name']}: {player['elo']} Elo\n"
                f"💔 {enemy['discord_name']}: {enemy['elo']} Elo"
            )
        else:
            await interaction.response.send_message("❌ Conflict in reports. Please cancel and agree on result.")
    else:
        pending_reports[key] = {
            "reporter": uid,
            "opponent": oid,
            "result": result
        }
        await interaction.response.send_message(
            f"📨 Report submitted. Waiting for {opponent.mention} to confirm using `/report {'lose' if result == 'win' else 'win'} @{interaction.user.name}`"
        )

# Cancel Report
@tree.command(name="cancel_report", description="Cancel a pending report")
async def cancel_report(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    to_remove = None
    for key, report in pending_reports.items():
        if report["reporter"] == uid or report["opponent"] == uid:
            to_remove = key
            break
    if to_remove:
        del pending_reports[to_remove]
        await interaction.response.send_message("✅ Report cancelled.")
    else:
        await interaction.response.send_message("No pending reports found.")

# Pending Reports
@tree.command(name="pending_reports", description="View your pending battle reports")
async def pending_reports_cmd(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    msg = ""
    for key, report in pending_reports.items():
        if report["reporter"] == uid:
            msg += f"🕒 You reported a **{report['result']}** vs <@{report['opponent']}>\n"
        elif report["opponent"] == uid:
            r = report["result"]
            msg += f"⚠️ <@{report['reporter']}> reported a **{r}** vs you. Confirm with `/report {'lose' if r == 'win' else 'win'} @{report['reporter']}`\n"
    await interaction.response.send_message(msg or "✅ No pending reports.")

# Leaderboard
@tree.command(name="leaderboard", description="See the top 10 Elo players")
async def leaderboard(interaction: discord.Interaction):
    data = load_data()
    sorted_data = sorted(data.items(), key=lambda x: x[1]["elo"], reverse=True)
    msg = "**🏆 Leaderboard:**\n"
    for i, (uid, u) in enumerate(sorted_data[:10], 1):
        msg += f"{i}. {u['discord_name']} — {u['elo']} Elo\n"
    await interaction.response.send_message(msg)

# Help
@tree.command(name="help_commands", description="View all commands")
async def help_commands(interaction: discord.Interaction):
    await interaction.response.send_message("""📘 **Commands:**

**🔧 Setup**
/register <username> — Register your Showdown name  
/cancel_register — Remove your registration  

**🎮 Matchmaking**
/matchmake — Join queue  
/cancelmatch — Leave queue  
/queue_status — See queue  

**⚔️ Battles**
/report win/lose @opponent — Report result  
/pending_reports — View pending reports  
/cancel_report — Cancel a report  

**📊 Stats**
/profile — View your stats  
/leaderboard — Top 10 players
""")

# Start bot
keep_alive()  # keep alive server for render
bot.run(TOKEN)
