import os
import discord
from discord.ext import commands
import json
import datetime
import asyncio
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from flask import Flask
import threading

# ===== 設定 =====
load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "data.json"

# ===== データ =====
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "guilds": {}}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()

# ===== ユーザー =====
def get_user(uid, gid):
    gid = str(gid)

    if gid not in data["users"]:
        data["users"][gid] = {}

    if uid not in data["users"][gid]:
        data["users"][gid][uid] = {
            "exp": 0,
            "total_minutes": 0,
            "study_start": None,
            "history": {},
            "streak": 0,
            "last_study_date": None
        }

    return data["users"][gid][uid]

def get_level(exp):
    return exp // 100 + 1

# ===== 勉強UI =====
class StudyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="▶ 勉強開始", style=discord.ButtonStyle.green)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = get_user(str(interaction.user.id), interaction.guild.id)

        if user["study_start"]:
            await interaction.response.send_message("すでに勉強中", ephemeral=True)
            return

        user["study_start"] = datetime.datetime.now().isoformat()
        save_data()
        await interaction.response.send_message("📚 勉強開始")

    @discord.ui.button(label="⏹ 勉強終了", style=discord.ButtonStyle.red)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = get_user(str(interaction.user.id), interaction.guild.id)

        if not user["study_start"]:
            await interaction.response.send_message("まだ開始してない", ephemeral=True)
            return

        start = datetime.datetime.fromisoformat(user["study_start"])
        minutes = int((datetime.datetime.now() - start).total_seconds() / 60)

        user["exp"] += minutes
        user["total_minutes"] += minutes

        today = str(datetime.date.today())
        yesterday = str(datetime.date.today() - datetime.timedelta(days=1))

        # ストリーク
        if user["last_study_date"] == yesterday:
            user["streak"] += 1
        elif user["last_study_date"] != today:
            user["streak"] = 1

        user["last_study_date"] = today

        # 履歴
        user["history"][today] = user["history"].get(today, 0) + minutes

        user["study_start"] = None
        save_data()

        await interaction.response.send_message(
            f"⏱ {minutes}分 / 🔥{user['streak']}日"
        )

# ===== パネル =====
@bot.tree.command(name="panel")
async def panel(interaction: discord.Interaction):
    await interaction.response.send_message("📚 勉強パネル", view=StudyView())

# ===== ステータス =====
@bot.tree.command(name="status")
async def status(interaction: discord.Interaction):
    user = get_user(str(interaction.user.id), interaction.guild.id)

    embed = discord.Embed(title="📊 ステータス")
    embed.add_field(name="時間", value=f"{user['total_minutes']}分")
    embed.add_field(name="EXP", value=f"{user['exp']}")
    embed.add_field(name="Lv", value=f"{get_level(user['exp'])}")
    embed.add_field(name="連続", value=f"{user['streak']}日")

    await interaction.response.send_message(embed=embed)

# ===== ランキング =====
@bot.tree.command(name="rank")
async def rank(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    users = data["users"].get(gid, {})

    sorted_users = sorted(users.items(), key=lambda x: x[1]["exp"], reverse=True)

    embed = discord.Embed(title="🏆 ランキング")

    for i, (uid, u) in enumerate(sorted_users[:10], 1):
        try:
            user = await bot.fetch_user(int(uid))
            name = user.name
        except:
            name = "Unknown"

        embed.add_field(name=f"{i}位 {name}", value=f"{u['exp']}EXP", inline=False)

    await interaction.response.send_message(embed=embed)

# ===== グラフ =====
@bot.tree.command(name="graph")
async def graph(interaction: discord.Interaction):
    user = get_user(str(interaction.user.id), interaction.guild.id)

    if not user["history"]:
        await interaction.response.send_message("データなし")
        return

    dates = list(user["history"].keys())
    values = list(user["history"].values())

    plt.figure()
    plt.plot(dates, values, marker="o")
    plt.xticks(rotation=45)

    plt.savefig("graph.png")
    plt.close()

    await interaction.response.send_message(file=discord.File("graph.png"))

# ===== VC勉強 =====
voice_sessions = {}

@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)

    if after.channel and not before.channel:
        voice_sessions[uid] = datetime.datetime.now()

    if before.channel and not after.channel:
        if uid in voice_sessions:
            start = voice_sessions[uid]
            minutes = int((datetime.datetime.now() - start).total_seconds() / 60)

            user = get_user(uid, member.guild.id)
            user["exp"] += minutes
            user["total_minutes"] += minutes

            del voice_sessions[uid]
            save_data()

# ===== ランキングチャンネル設定 =====
@bot.tree.command(name="setrankchannel")
async def setrankchannel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("権限なし", ephemeral=True)
        return

    gid = str(interaction.guild.id)

    if gid not in data["guilds"]:
        data["guilds"][gid] = {}

    data["guilds"][gid]["rank_channel"] = interaction.channel.id
    save_data()

    await interaction.response.send_message("✅ 設定完了")

# ===== 今日ランキング =====
def get_today_ranking(gid):
    users = data["users"].get(gid, {})
    today = str(datetime.date.today())

    ranking = []
    for uid, u in users.items():
        minutes = u["history"].get(today, 0)
        if minutes > 0:
            ranking.append((uid, minutes))

    return sorted(ranking, key=lambda x: x[1], reverse=True)[:10]

# ===== 自動投稿 =====
async def daily_ranking():
    await bot.wait_until_ready()

    while not bot.is_closed():
        now = datetime.datetime.now()

        if now.hour == 23 and now.minute == 59:
            for gid in data["guilds"]:
                channel_id = data["guilds"][gid].get("rank_channel")

                if not channel_id:
                    continue

                channel = bot.get_channel(channel_id)
                if not channel:
                    continue

                ranking = get_today_ranking(gid)
                if not ranking:
                    continue

                embed = discord.Embed(title="🏆 今日のランキング")

                for i, (uid, minutes) in enumerate(ranking, 1):
                    try:
                        user = await bot.fetch_user(int(uid))
                        name = user.name
                    except:
                        name = "Unknown"

                    if i == 1:
                        name = "👑 " + name

                    embed.add_field(
                        name=f"{i}位 {name}",
                        value=f"{minutes}分",
                        inline=False
                    )

                await channel.send(embed=embed)

        await asyncio.sleep(60)

# ===== Flask（24時間用）=====
app = Flask(__name__)

@app.route("/")
def home():
    return "OK"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run).start()

# ===== 起動 =====
@bot.event
async def on_ready():
    await bot.tree.sync()
    bot.loop.create_task(daily_ranking())
    print("起動完了")

bot.run(TOKEN)
