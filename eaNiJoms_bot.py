import discord
from discord.ext import tasks, commands
from datetime import datetime
import pytz
import asyncio
import json
import os
import time
from dotenv import load_dotenv

# =========================================================
# ✅ LOAD ENV VARIABLES
# =========================================================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# =========================================================
# ✅ CONFIG
# =========================================================
TARGET_USER_ID = 503046664555069440
REMINDER_CHANNEL_ID = 1310518792291614740
VOICE_CHANNEL_ID = 1326549055110905976
PAU_USER_ID = 289570358560948225
BOT_USER_ID = 1433450577177608345

DATA_FILE = "voice_data.json"

# =========================================================
# ✅ BOT SETUP
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)  # remove default !help
ph_tz = pytz.timezone("Asia/Manila")

voice_sessions = {}     # {user_id: join_timestamp}
daily_totals = {}       # {user_id: seconds}
all_time_totals = {}    # {user_id: seconds}


# =========================================================
# ✅ LOAD & SAVE FUNCTIONS
# =========================================================
def save_data():
    data = {
        "active_sessions": voice_sessions,
        "daily_totals": daily_totals,
        "all_time_totals": all_time_totals
    }
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
        print("💾 Saved voice tracking data.")
    except Exception as e:
        print(f"⚠️ Failed to save data: {e}")


def load_data():
    global voice_sessions, daily_totals, all_time_totals

    if not os.path.exists(DATA_FILE):
        print("📁 No previous data found. Starting fresh.")
        return

    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)

        voice_sessions = data.get("active_sessions", {})
        daily_totals = data.get("daily_totals", {})
        all_time_totals = data.get("all_time_totals", {})

        print("✅ Loaded saved voice tracking data.")
    except Exception as e:
        print(f"⚠️ Failed to load data: {e}")


# =========================================================
# ✅ BOT READY EVENT
# =========================================================
@bot.event
async def on_ready():
    print(f"✅ Ea ni Joms is online as {bot.user}")
    load_data()

    now_ts = int(time.time())
    channel = bot.get_channel(VOICE_CHANNEL_ID)

    if channel:
        members = [m for m in channel.members if not m.bot]
        if members:
            for member in members:
                voice_sessions[member.id] = now_ts
                daily_totals.setdefault(str(member.id), 0)
                all_time_totals.setdefault(str(member.id), 0)
                print(f"🕒 Detected {member.name} already in channel at startup.")
        else:
            print("🔇 No one in channel at startup.")
    else:
        print("⚠️ Voice channel not found on startup.")

    send_reminders.start()
    daily_report.start()
    periodic_save.start()
    update_ongoing_sessions.start()


# =========================================================
# ✅ TRACK JOIN / LEAVE
# =========================================================
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    now_ts = int(time.time())

    # --- User JOINED the target voice channel ---
    if before.channel != after.channel:
        if after.channel and after.channel.id == VOICE_CHANNEL_ID:
            # Joined our target channel
            if member.id not in voice_sessions:
                voice_sessions[member.id] = now_ts
                print(f"🎧 {member.name} joined voice.")
        
        # --- User LEFT the target voice channel ---
        elif before.channel and before.channel.id == VOICE_CHANNEL_ID and (not after.channel or after.channel.id != VOICE_CHANNEL_ID):
            if member.id in voice_sessions:
                join_ts = voice_sessions.pop(member.id)
                duration = now_ts - join_ts

                daily_totals[str(member.id)] = daily_totals.get(str(member.id), 0) + duration
                all_time_totals[str(member.id)] = all_time_totals.get(str(member.id), 0) + duration

                print(f"👋 {member.name} left voice after {duration // 60}m.")
                save_data()

# =========================================================
# ✅ UPDATE ONGOING SESSIONS
# =========================================================
@tasks.loop(minutes=1)
async def update_ongoing_sessions():
    channel = bot.get_channel(VOICE_CHANNEL_ID)
    if not channel:
        return

    for member in channel.members:
        if member.bot:
            continue

        if member.id not in voice_sessions:
            voice_sessions[member.id] = int(time.time())
            print(f"🕓 Added missing session for {member.name}")

        daily_totals[str(member.id)] = daily_totals.get(str(member.id), 0) + 60
        all_time_totals[str(member.id)] = all_time_totals.get(str(member.id), 0) + 60

    save_data()


# =========================================================
# ✅ DAILY REMINDERS
# =========================================================
@tasks.loop(minutes=1)
async def send_reminders():
    now = datetime.now(ph_tz)
    current_time = now.strftime("%H:%M")

    channel = bot.get_channel(REMINDER_CHANNEL_ID)
    user = await bot.fetch_user(TARGET_USER_ID)

    if current_time == "12:00":
        await channel.send(f"🍱 Hey {user.mention}! Lunch time na 😋")
    elif current_time == "19:00":
        await channel.send(f"🍽️ Hey {user.mention}! Dinner time na 😄")


# =========================================================
# ✅ DAILY REPORT
# =========================================================
@tasks.loop(minutes=1)
async def daily_report():
    now = datetime.now(ph_tz)

    if now.strftime("%H:%M") == "00:00":
        channel = bot.get_channel(REMINDER_CHANNEL_ID)

        if not daily_totals:
            await channel.send("📊 Walang nag-duty kahapon 😴")
        else:
            lines = ["📅 **Daily Duty Report (Yesterday)**\n"]
            for uid, seconds in daily_totals.items():
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                lines.append(f"• <@{uid}> — {hours}h {minutes}m")

            await channel.send("\n".join(lines))

        daily_totals.clear()
        save_data()
        await asyncio.sleep(61)


# =========================================================
# ✅ LEADERBOARD COMMAND
# =========================================================
@bot.command(name="Sekyu")
async def sekyu(ctx):
    if not all_time_totals:
        await ctx.send("📊 Walang laman ang leaderboard 😅")
        return

    top10 = sorted(all_time_totals.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = ["🏆 **ALL-TIME SEKYU LEADERBOARDS — TOP 10**\n"]

    for i, (uid, seconds) in enumerate(top10, 1):
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        lines.append(f"**{i}. <@{uid}>** — {hours}h {minutes}m")

    await ctx.send("\n".join(lines))

# =========================================================
# ✅ SINONGMAHALMO COMMAND
# =========================================================
@bot.command(name="SinongMahalMo")
async def sinongmahalmo(ctx):
    user = await bot.fetch_user(TARGET_USER_ID)
    embed = discord.Embed(
        title="💙 Sinong Mahal Mo?",
        description=(
            f"Syempre ang **pinakaloveable 💖**, **pinakajowable 😍**, "
            f"at **pinakabluehair 💙** na si **G_DRAGON** **{user.name}**! ✨"
        ),
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.set_footer(text="Certified ni Ea ni Joms 💙")
    await ctx.send(embed=embed)


# =========================================================
# ✅ SINONGMAHALNIJOMS COMMAND
# =========================================================
@bot.command(name="SinongMahalNiJoms")
async def sinongmahalnijoms(ctx):
    target_user = await bot.fetch_user(TARGET_USER_ID)
    pau_user = await bot.fetch_user(PAU_USER_ID)
    bot_user = await bot.fetch_user(BOT_USER_ID)

    embed = discord.Embed(
        title="💞 Sinong Mahal Ni Joms?",
        description=(
            f"Ang pinakamamahal ni **{target_user.name}** ay si **{bot_user.name}**💙, "
            f"at syempre, walang tatalo sa pagmamahal niya sakaniyang idol na si **{pau_user.name}**."
            f"**Joms Loves you Both So Much** 😎✨"
        ),
        color=discord.Color.from_rgb(173, 216, 230)
    )
    embed.set_footer(text="Spread the love 💞 — Ea ni Joms Bot")
    await ctx.send(embed=embed)



# =========================================================
# ✅ BLUEHAIR COMMAND
# =========================================================
@bot.command(name="BlueHair")
async def bluehair(ctx):
    embed = discord.Embed(
        title="💙 Ea ni Joms — Command Reference",
        description="Here's everything I can do for you! ✨",
        color=discord.Color.from_rgb(30, 144, 255)
    )

    embed.add_field(
        name="👮‍♂️ !Sekyu",
        value="Show the **All-Time Sekyu Leaderboards (Top 10)**.",
        inline=False
    )

    embed.add_field(
        name="💘 !SinongMahalMo",
        value="Shows how much **Ea ni Joms** loves his favorite blue-haired idol 💙",
        inline=False
    )

    embed.add_field(
        name="💞 !SinongMahalNiJoms",
        value="Reveals who **Ea ni Joms** truly loves and idolizes 💖",
        inline=False
    )

    embed.add_field(
        name="🔁 Automatic Features",
        value=(
            "• **Lunch Reminder** → 12:00 PM 🍱\n"
            "• **Dinner Reminder** → 7:00 PM 🍽️\n"
            "• **Daily Duty Report** → Every Midnight 🕛\n"
            "• **Voice Time Tracking** → Auto-updates every minute ⏱️"
        ),
        inline=False
    )

    embed.add_field(
        name="ℹ️ Tip",
        value="Need to check what I can do again? Just type **!BlueHair** 💫",
        inline=False
    )

    embed.set_footer(text="Made with 💙 by Ea ni Joms Bot")

    await ctx.send(embed=embed)


# =========================================================
# ✅ PERIODIC SAVE
# =========================================================
@tasks.loop(minutes=1)
async def periodic_save():
    save_data()


# =========================================================
# ✅ RUN BOT
# =========================================================
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ No DISCORD_TOKEN found. Please check your .env file.")
