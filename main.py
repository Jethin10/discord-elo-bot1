import discord
from discord import app_commands
from discord.ext import commands
import os
import json

# Get token from environment variable
TOKEN = os.getenv("DISCORD_TOKEN")

# Set up bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Database file & matchmaking queue
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

# Sync slash commands
@bot.event
async def on_ready():
    await bot.wait_until_ready()
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")
    print(f"🎮 Bot is online: {bot.user}")

# /register
@bot.tree.command(name="register", description="Register your Pokémon Showdown username.")
async def register(interaction: discord.Interaction, showdown_name: str):
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id in data:
        await interaction.response.send_message("⚠️ You're already registered.")
        return

    data[user_id] = {
        "discord_name": interaction.user.name,
        "showdown_name": showdown_name,
        "elo": 1000,
        "wins": 0,
        "losses": 0
    }
    save_data(data)
    await interaction.response.send_message(f"✅ Registered as `{showdown_name}` with 1000 Elo.")

# /cancel_register
@bot.tree.command(name="cancel_register", description="Remove your account and data.")
async def cancel_register(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.response.send_message("❌ You're not registered.")
        return

    queue[:] = [uid for uid in queue if uid != user_id]

    keys_to_remove = [k for k in pending_reports if user_id in k]
    for k in keys_to_remove:
        del pending_reports[k]

    del data[user_id]
    save_data(data)

    await interaction.response.send_message("🗑️ Your data has been deleted. You're no longer registered.")

# /profile
@bot.tree.command(name="profile", description="See your stats and Showdown name.")
async def profile(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.response.send_message("❌ You're not registered.")
        return

    user = data[user_id]
    await interaction.response.send_message(
        f"📊 **Profile: {user['discord_name']}**\n"
        f"🧢 Showdown: `{user['showdown_name']}`\n"
        f"🏅 Elo: {user['elo']}\n"
        f"⚔️ Record: {user['wins']}W / {user['losses']}L"
    )

# /matchmake
@bot.tree.command(name="matchmake", description="Enter the ranked matchmaking queue.")
async def matchmake(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.response.send_message("❌ Register first with `/register`.")
        return

    if user_id in queue:
        await interaction.response.send_message("⚠️ You're already in the queue.")
        return

    queue.append(user_id)
    await interaction.response.send_message("🔍 Searching for a match...")

    # Try to find opponent
    player = data[user_id]
    best_match = None
    best_diff = 9999

    for other_id in queue:
        if other_id == user_id:
            continue
        opponent = data[other_id]
        diff = abs(player["elo"] - opponent["elo"])
        if diff <= 150 and diff < best_diff:
            best_match = other_id
            best_diff = diff

    if best_match:
        queue.remove(user_id)
        queue.remove(best_match)
        p1, p2 = data[user_id], data[best_match]

        await interaction.followup.send(
            f"🎉 **Match Found!**\n"
            f"<@{user_id}> (`{p1['showdown_name']}`) **vs** <@{best_match}> (`{p2['showdown_name']}`)\n"
            f"🔗 Go to https://play.pokemonshowdown.com/ and challenge each other!\n"
            f"📝 After the match, use `/report win @opponent` or `/report lose @opponent`"
        )

# /cancelmatch
@bot.tree.command(name="cancelmatch", description="Leave the matchmaking queue.")
async def cancelmatch(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id in queue:
        queue.remove(user_id)
        await interaction.response.send_message("❌ You left the matchmaking queue.")
    else:
        await interaction.response.send_message("⚠️ You're not in the queue.")

# /report
@bot.tree.command(name="report", description="Report match result (confirmation needed).")
@app_commands.describe(result="Choose 'win' or 'lose'", opponent="Your opponent")
async def report(interaction: discord.Interaction, result: str, opponent: discord.Member):
    data = load_data()
    uid, oid = str(interaction.user.id), str(opponent.id)
    result = result.lower()

    if uid not in data or oid not in data:
        await interaction.response.send_message("❌ Both players must be registered.")
        return

    if result not in ["win", "lose"]:
        await interaction.response.send_message("⚠️ Result must be `win` or `lose`.")
        return

    key = f"{min(uid, oid)}_{max(uid, oid)}"

    # Confirm if both agree
    if key in pending_reports:
        report_data = pending_reports[key]
        if report_data["reporter"] == oid and report_data["result"] != result:
            p1, p2 = data[uid], data[oid]
            K = 32
            expected = 1 / (1 + 10 ** ((p2["elo"] - p1["elo"]) / 400))
            delta = round(K * (1 - expected)) if result == "win" else round(K * expected)

            if result == "win":
                p1["elo"] += delta
                p2["elo"] -= delta
                p1["wins"] += 1
                p2["losses"] += 1
            else:
                p1["elo"] -= delta
                p2["elo"] += delta
                p1["losses"] += 1
                p2["wins"] += 1

            save_data(data)
            del pending_reports[key]

            await interaction.response.send_message(
                f"✅ Match confirmed. Elo updated!\n"
                f"🏆 {p1['discord_name']}: {p1['elo']} Elo\n"
                f"😓 {p2['discord_name']}: {p2['elo']} Elo"
            )
        else:
            await interaction.response.send_message("❌ Conflict! Please cancel the report with `/cancel_report` and try again.")
    else:
        pending_reports[key] = {
            "reporter": uid,
            "opponent": oid,
            "result": result
        }
        await interaction.response.send_message(
            f"📝 Report submitted! Waiting for {opponent.mention} to confirm.\n"
            f"Use `/report {'lose' if result == 'win' else 'win'} @{interaction.user.name}` to confirm."
        )

# /cancel_report
@bot.tree.command(name="cancel_report", description="Cancel a pending match report.")
async def cancel_report(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    to_cancel = None
    for k, v in pending_reports.items():
        if uid == v["reporter"] or uid == v["opponent"]:
            to_cancel = k
            break
    if to_cancel:
        del pending_reports[to_cancel]
        await interaction.response.send_message("🗑️ Pending match report cancelled.")
    else:
        await interaction.response.send_message("No report found to cancel.")

# /leaderboard
@bot.tree.command(name="leaderboard", description="See top players by Elo.")
async def leaderboard(interaction: discord.Interaction):
    data = load_data()
    sorted_data = sorted(data.items(), key=lambda x: x[1]["elo"], reverse=True)
    msg = "**🏆 Leaderboard:**\n"
    for i, (uid, u) in enumerate(sorted_data[:10], 1):
        msg += f"{i}. {u['discord_name']} - {u['elo']} Elo\n"
    await interaction.response.send_message(msg)

# /queue_status
@bot.tree.command(name="queue_status", description="Who's waiting in queue.")
async def queue_status(interaction: discord.Interaction):
    if not queue:
        await interaction.response.send_message("🕒 Queue is empty.")
        return
    data = load_data()
    msg = "**🎮 Current Queue:**\n"
    for i, uid in enumerate(queue, 1):
        user = data.get(uid)
        if user:
            msg += f"{i}. {user['discord_name']} - {user['elo']} Elo\n"
    await interaction.response.send_message(msg)

# /help_commands
@bot.tree.command(name="help_commands", description="List all available commands.")
async def help_commands(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**📘 Pokémon Elo Bot Commands:**\n\n"
        "🛠️ `/register <ps_name>` — Register your account\n"
        "🧢 `/profile` — View your stats\n"
        "🔁 `/matchmake` — Enter matchmaking\n"
        "❌ `/cancelmatch` — Leave queue\n"
        "📊 `/leaderboard` — Top 10 players\n"
        "⚔️ `/report <win/lose> @opponent` — Submit battle result\n"
        "⏳ `/cancel_report` — Cancel a report\n"
        "🚫 `/cancel_register` — Delete your data"
    )

# Run the bot
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ DISCORD_TOKEN environment variable not set.")
