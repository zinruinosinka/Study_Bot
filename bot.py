import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

import json
import datetime
import matplotlib.pyplot as plt
import asyncio

# ===== .env読み込み =====
load_dotenv()

# ===== intents =====
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ===== データ =====
DATA_FILE = "data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

data = load_data()

# ===== ユーザー管理 =====
def get_user(uid, gid):
    gid = str(gid)
    uid = str(uid)

    if gid not in data["users"]:
        data["users"][gid] = {}

    if uid not in data["users"][gid]:
        data["users"][gid][uid] = {
            "exp": 0,
            "study_start": None,
            "history": {},
            "streak": 0,
            "last_study_date": None
        }

    return data["users"][gid][uid]

# ===== レベル =====
def get_level(exp):
    return exp // 100 + 1

# ===== VC記録 =====
voice_sessions = {}

# ===== UI =====
class StudyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="▶ 勉強開始", style=discord.ButtonStyle.green)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):

        user = get_user(interaction.user.id, interaction.guild.id)

        if user["study_start"]:
            await interaction.response.send_message("すでに勉強中！", ephemeral=True)
            return

        user["study_start"] = datetime.datetime.now().isoformat()
        save_data()

        await interaction.response.send_message("📚 勉強開始！")

    @discord.ui.button(label="⏹ 勉強終了", style=discord.ButtonStyle.red)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):

        user = get_user(interaction.user.id, interaction.guild.id)

        if not user["study_start"]:
            await interaction.response.send_message("まだ開始してない！", ephemeral=True)
            return

        start = datetime.datetime.fromisoformat(user["study_start"])
        minutes = int((datetime.datetime.now() - start).total_seconds() / 60)

        before = get_level(user["exp"])
        user["exp"] += minutes
        after = get_level(user["exp"])

        today = str(datetime.date.today())
        yesterday = str(datetime.date.today() - datetime.timedelta(days=1))

        if user["last_study_date"] == yesterday:
            user["streak"] += 1
        elif user["last_study_date"] != today:
            user["streak"] = 1

        user["last_study_date"] = today

        user["history"][today] = user["history"].get(today, 0) + minutes

        user["study_start"] = None

        save_data()

        msg = f"⏱ {minutes}分\n合計: {user['exp']}分 Lv:{after}\n🔥 ストリーク:{user['streak']}"

        if after > before:
            msg += "\n🎉 レベルアップ！"

        await interaction.response.send_message(msg)

# ===== 起動 =====
@bot.event
async def on_ready():
    print(f"ログイン: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュ同期: {len(synced)}個")
    except Exception as e:
        print(e)

# ===== panel =====
@bot.tree.command(name="panel", description="勉強パネル")
async def panel(interaction: discord.Interaction):
    embed = discord.Embed(title="📚 勉強パネル", color=discord.Color.green())
    await interaction.response.send_message(embed=embed, view=StudyView())

# ===== status =====
@bot.tree.command(name="status", description="ステータス")
async def status(interaction: discord.Interaction):
    user = get_user(interaction.user.id, interaction.guild.id)
    level = get_level(user["exp"])

    embed = discord.Embed(title="📊 ステータス")
    embed.add_field(name="時間", value=f"{user['exp']}分")
    embed.add_field(name="Lv", value=level)
    embed.add_field(name="連続", value=f"{user['streak']}日")

    await interaction.response.send_message(embed=embed)

# ===== now =====
@bot.tree.command(name="now", description="勉強中時間")
async def now(interaction: discord.Interaction):
    user = get_user(interaction.user.id, interaction.guild.id)

    if not user["study_start"]:
        await interaction.response.send_message("勉強してない")
        return

    start = datetime.datetime.fromisoformat(user["study_start"])
    minutes = int((datetime.datetime.now() - start).total_seconds() / 60)

    await interaction.response.send_message(f"{minutes}分経過")

# ===== rank =====
@bot.tree.command(name="rank", description="ランキング")
async def rank(interaction: discord.Interaction):
    users = data["users"].get(str(interaction.guild.id), {})

    sorted_users = sorted(users.items(), key=lambda x: x[1]["exp"], reverse=True)

    embed = discord.Embed(title="🏆 ランキング")

    for i, (uid, u) in enumerate(sorted_users[:10], 1):
        try:
            user = await bot.fetch_user(int(uid))
            name = user.name
        except:
            name = "Unknown"

        embed.add_field(name=f"{i}位 {name}", value=f"{u['exp']}分", inline=False)

    await interaction.response.send_message(embed=embed)

# ===== graph =====
@bot.tree.command(name="graph", description="グラフ")
async def graph(interaction: discord.Interaction):
    user = get_user(interaction.user.id, interaction.guild.id)

    if not user["history"]:
        await interaction.response.send_message("データなし")
        return

    dates = list(user["history"].keys())
    values = list(user["history"].values())

    plt.figure()
    plt.plot(dates, values, marker="o")
    plt.xticks(rotation=45)

    file = "graph.png"
    plt.savefig(file)
    plt.close()

    await interaction.response.send_message(file=discord.File(file))

# ===== VC =====
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

            del voice_sessions[uid]
            save_data()

# ===== 起動 =====
from dotenv import load_dotenv
import os

load_dotenv()

token = os.getenv("TOKEN")

bot.run(token)