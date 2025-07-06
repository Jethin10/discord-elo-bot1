import discord
from discord.ext import commands
from flask import Flask
from threading import Thread
import json
import os

# Set up Flask server to keep bot alive (for Render)
app = Flask('')
@app.route('/')
def home():
    return "Hello, I am alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Discord bot setup
intents = discord.Intents.default()
intents.members = True  # enable members intent if needed
bot = commands.Bot(intents=intents)

# Data file path
DATA_FILE = 'data.json'

# Load data from JSON file, or create default if not exists
def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {"users": {}, "queue": [], "pending_reports": []}
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f)
    return data

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# Utility to get Discord user object from ID (fetch if not in cache)
async def get_user_or_fetch(user_id):
    user = bot.get_user(int(user_id))
    if user is None:
        try:
            user = await bot.fetch_user(int(user_id))
        except discord.NotFound:
            user = None
    return user

# Register command
@bot.slash_command(name="register", description="Register a user with a Showdown username")
async def register(ctx, showdown_name: str):
    await ctx.defer()
    data = load_data()
    user_id = str(ctx.author.id)
    if user_id in data["users"]:
        await ctx.followup.send(f"You are already registered as '{data['users'][user_id]['showdown_name']}'.", ephemeral=True)
        return
    # Initialize user data
    data["users"][user_id] = {
        "showdown_name": showdown_name,
        "elo": 1000,
        "wins": 0,
        "losses": 0
    }
    save_data(data)
    await ctx.followup.send(f"Registered '{showdown_name}' with Elo 1000.", ephemeral=True)

# Cancel register command
@bot.slash_command(name="cancel_register", description="Delete your registration and data")
async def cancel_register(ctx):
    await ctx.defer()
    data = load_data()
    user_id = str(ctx.author.id)
    if user_id not in data["users"]:
        await ctx.followup.send("You are not registered.", ephemeral=True)
        return
    # Remove user data
    del data["users"][user_id]
    # Remove from queue if present
    if user_id in data["queue"]:
        data["queue"].remove(user_id)
    # Remove pending reports involving user
    data["pending_reports"] = [r for r in data["pending_reports"] if r["reporter"] != user_id and r["opponent"] != user_id]
    save_data(data)
    await ctx.followup.send("Your registration and data have been deleted.", ephemeral=True)

# Profile command
@bot.slash_command(name="profile", description="Show your Showdown username, Elo, and win/loss record")
async def profile(ctx):
    await ctx.defer()
    data = load_data()
    user_id = str(ctx.author.id)
    if user_id not in data["users"]:
        await ctx.followup.send("You are not registered. Use /register to sign up.", ephemeral=True)
        return
    user_data = data["users"][user_id]
    name = user_data["showdown_name"]
    elo = user_data["elo"]
    wins = user_data["wins"]
    losses = user_data["losses"]
    await ctx.followup.send(f"**Showdown Name:** {name}\n**Elo:** {elo}\n**Record:** {wins}W-{losses}L", ephemeral=True)

# Matchmaking queue command
@bot.slash_command(name="matchmake", description="Join the ranked matchmaking queue")
async def matchmake(ctx):
    await ctx.defer()
    data = load_data()
    user_id = str(ctx.author.id)
    # Check registration
    if user_id not in data["users"]:
        await ctx.followup.send("You must register first using /register.", ephemeral=True)
        return
    # Check if already in queue
    if user_id in data["queue"]:
        await ctx.followup.send("You are already in the queue.", ephemeral=True)
        return
    # Add to queue
    data["queue"].append(user_id)
    save_data(data)
    # Try to find a match
    me_data = data["users"][user_id]
    match_found = None
    for other_id in data["queue"]:
        if other_id == user_id:
            continue
        other_data = data["users"].get(other_id)
        if other_data and abs(me_data["elo"] - other_data["elo"]) <= 150:
            match_found = other_id
            break
    if match_found:
        # Match found
        other_id = match_found
        data["queue"].remove(user_id)
        data["queue"].remove(other_id)
        save_data(data)
        user = ctx.author
        other_user = await get_user_or_fetch(other_id)
        await ctx.followup.send(f"Match found! You vs {other_user.mention}. Good luck!", ephemeral=True)
        # Inform the other user via DM
        if other_user:
            try:
                await other_user.send(f"You have been matched with {user.mention}! Good luck!")
            except:
                pass
    else:
        # No match yet
        await ctx.followup.send("You have been added to the queue. Waiting for a match...", ephemeral=True)

# Cancel matchmaking
@bot.slash_command(name="cancelmatch", description="Leave the matchmaking queue")
async def cancelmatch(ctx):
    await ctx.defer()
    data = load_data()
    user_id = str(ctx.author.id)
    if user_id not in data["queue"]:
        await ctx.followup.send("You are not in the queue.", ephemeral=True)
        return
    data["queue"].remove(user_id)
    save_data(data)
    await ctx.followup.send("You have been removed from the queue.", ephemeral=True)

# Queue status
@bot.slash_command(name="queue_status", description="Show all current players in the matchmaking queue")
async def queue_status(ctx):
    await ctx.defer()
    data = load_data()
    if not data["queue"]:
        await ctx.followup.send("The queue is empty.", ephemeral=False)
        return
    msg = "**Queue:**\n"
    for uid in data["queue"]:
        user_data = data["users"].get(uid)
        if user_data:
            name = user_data["showdown_name"]
            elo = user_data["elo"]
            member = await get_user_or_fetch(uid)
            mention = member.mention if member else uid
            msg += f"- {mention} (Showdown: {name}, Elo: {elo})\n"
    await ctx.followup.send(msg, ephemeral=False)

# Battle reporting
@bot.slash_command(name="report", description="Submit a battle result (requires opponent confirmation)")
async def report(ctx, outcome: str, opponent: discord.Member):
    await ctx.defer()
    data = load_data()
    reporter_id = str(ctx.author.id)
    opp_id = str(opponent.id)
    # Check users
    if reporter_id not in data["users"] or opp_id not in data["users"]:
        await ctx.followup.send("Both players must be registered.", ephemeral=True)
        return
    if reporter_id == opp_id:
        await ctx.followup.send("You cannot report a match against yourself.", ephemeral=True)
        return
    if outcome.lower() not in ["win", "lose"]:
        await ctx.followup.send("Invalid result. Use 'win' or 'lose'.", ephemeral=True)
        return
    pending = data["pending_reports"]
    # Check if reporter already reported this match
    for r in pending:
        if r["reporter"] == reporter_id and r["opponent"] == opp_id:
            await ctx.followup.send("You have already reported this match and it's pending.", ephemeral=True)
            return
    # Check if opponent has reported opposite outcome
    for r in pending:
        if r["reporter"] == opp_id and r["opponent"] == reporter_id:
            # Opponent has reported this match; check if results match
            if (r["result"] == "win" and outcome.lower() == "lose") or (r["result"] == "lose" and outcome.lower() == "win"):
                # Confirm match and update Elo
                if outcome.lower() == "win":
                    winner_id = reporter_id
                    loser_id = opp_id
                else:
                    winner_id = opp_id
                    loser_id = reporter_id
                winner_data = data["users"][winner_id]
                loser_data = data["users"][loser_id]
                R_w = winner_data["elo"]
                R_l = loser_data["elo"]
                E_w = 1 / (1 + 10 ** ((R_l - R_w) / 400))
                E_l = 1 / (1 + 10 ** ((R_w - R_l) / 400))
                K = 32
                winner_data["elo"] = round(R_w + K * (1 - E_w))
                loser_data["elo"] = round(R_l + K * (0 - E_l))
                winner_data["wins"] += 1
                loser_data["losses"] += 1
                data["pending_reports"] = [x for x in pending if not ((x["reporter"] == opp_id and x["opponent"] == reporter_id) or (x["reporter"] == reporter_id and x["opponent"] == opp_id))]
                save_data(data)
                # Identify winner and loser members
                winner_member = ctx.author if winner_id == reporter_id else opponent
                loser_member = opponent if winner_id == reporter_id else ctx.author
                await ctx.followup.send("Match result confirmed! Elo and records have been updated.", ephemeral=True)
                try:
                    await winner_member.send(f"Your win against {loser_member.mention} has been confirmed! New Elo: {winner_data['elo']}")
                except:
                    pass
                try:
                    await loser_member.send(f"Your loss to {winner_member.mention} has been confirmed. New Elo: {loser_data['elo']}")
                except:
                    pass
                return
            else:
                await ctx.followup.send("There is a conflicting report by your opponent. Please check /pending_reports.", ephemeral=True)
                return
    # No existing opponent report; create new pending
    data["pending_reports"].append({"reporter": reporter_id, "opponent": opp_id, "result": outcome.lower()})
    save_data(data)
    await ctx.followup.send("Result submitted. Awaiting opponent confirmation.", ephemeral=True)

# Pending reports
@bot.slash_command(name="pending_reports", description="View your pending match results")
async def pending_reports(ctx):
    await ctx.defer()
    data = load_data()
    user_id = str(ctx.author.id)
    pending = data["pending_reports"]
    # Pending you submitted
    submitted = [r for r in pending if r["reporter"] == user_id]
    # Pending awaiting your confirmation
    awaiting = [r for r in pending if r["opponent"] == user_id]
    if not submitted and not awaiting:
        await ctx.followup.send("You have no pending reports.", ephemeral=True)
        return
    msg = ""
    if submitted:
        msg += "**Reports you submitted (awaiting opponent):**\n"
        for r in submitted:
            opp_user = await get_user_or_fetch(r["opponent"])
            msg += f"- vs {opp_user.mention if opp_user else r['opponent']}: {r['result']}\n"
    if awaiting:
        msg += "**Reports awaiting your confirmation:**\n"
        for r in awaiting:
            rep_user = await get_user_or_fetch(r["reporter"])
            result_text = "win" if r["result"] == "lose" else "loss"
            msg += f"- {rep_user.mention if rep_user else r['reporter']} reported a {result_text} for you\n"
    await ctx.followup.send(msg, ephemeral=True)

# Cancel report
@bot.slash_command(name="cancel_report", description="Cancel your submitted report")
async def cancel_report(ctx):
    await ctx.defer()
    data = load_data()
    user_id = str(ctx.author.id)
    pending = data["pending_reports"]
    original_len = len(pending)
    data["pending_reports"] = [r for r in pending if r["reporter"] != user_id]
    if len(data["pending_reports"]) == original_len:
        await ctx.followup.send("You have no pending reports to cancel.", ephemeral=True)
    else:
        save_data(data)
        await ctx.followup.send("Your pending report has been canceled.", ephemeral=True)

# Leaderboard
@bot.slash_command(name="leaderboard", description="Show the top 10 players by Elo")
async def leaderboard(ctx):
    await ctx.defer()
    data = load_data()
    users = list(data["users"].items())
    if not users:
        await ctx.followup.send("No registered players.", ephemeral=False)
        return
    sorted_users = sorted(users, key=lambda x: x[1]["elo"], reverse=True)
    top = sorted_users[:10]
    msg = "**Leaderboard (Top 10 by Elo):**\n"
    rank = 1
    for uid, user_data in top:
        user = await get_user_or_fetch(uid)
        mention = user.mention if user else uid
        name = user_data["showdown_name"]
        elo = user_data["elo"]
        win = user_data["wins"]
        loss = user_data["losses"]
        msg += f"{rank}. {mention} (Showdown: {name}) - Elo: {elo} ({win}W-{loss}L)\n"
        rank += 1
    await ctx.followup.send(msg, ephemeral=False)

# Help commands
@bot.slash_command(name="help_commands", description="Show a summary of all bot commands")
async def help_commands(ctx):
    await ctx.defer()
    help_text = (
        "**Pok\u00e9mon Showdown Matchmaking Bot Commands:**\n"
        "• `/register <showdown_name>`: Register with your Showdown username.\n"
        "• `/cancel_register`: Delete your registration and data.\n"
        "• `/profile`: Show your Showdown username, Elo, and win/loss record.\n"
        "• `/matchmake`: Join the ranked matchmaking queue.\n"
        "• `/cancelmatch`: Leave the matchmaking queue.\n"
        "• `/queue_status`: Show current players in the matchmaking queue.\n"
        "• `/report <win|lose> @opponent`: Submit a battle result. Requires opponent confirmation.\n"
        "• `/pending_reports`: View your pending match results.\n"
        "• `/cancel_report`: Cancel your submitted report.\n"
        "• `/leaderboard`: Show the top 10 players by Elo.\n"
        "• `/help_commands`: Show this help message."
    )
    await ctx.followup.send(help_text, ephemeral=True)

# On ready event
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# Start keep_alive and run bot
keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
