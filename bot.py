import os
import discord
from discord.ext import commands
import json
import datetime
import matplotlib.pyplot as plt
import asyncio
from dotenv import load_dotenv

# ===== .env読み込み =====
load_dotenv()
TOKEN = os.getenv("TOKEN")

# ===== Intent =====
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "data.json"

# ===== データ =====
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()

# ===== ユーザー取得 =====
def get_user(uid, gid):
    gid = str(gid)

    if gid not in data["users"]:
        data["users"][gid] = {}

    if uid not in data["users"][gid]:
        data["users"][gid][uid] = {
            "exp": 0,
            "study_start": None,
            "history": {},
            "streak": 0,
            "last_study_date": None,
            "is_premium": False
        }

    return data["users"][gid][uid]

# ===== レベル =====
def get_level(exp):
    return exp // 100 + 1

# ===== UI =====
class StudyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="▶ 勉強開始", style=discord.ButtonStyle.green)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = get_user(str(interaction.user.id), interaction.guild.id)

        if user["study_start"]:
            await interaction.response.send_message("すでに勉強中！", ephemeral=True)
            return

        user["study_start"] = datetime.datetime.now().isoformat()
        save_data()

        await interaction.response.send_message("📚 勉強開始！")

    @discord.ui.button(label="⏹ 勉強終了", style=discord.ButtonStyle.red)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = get_user(str(interaction.user.id), interaction.guild.id)

        if not user["study_start"]:
            await interaction.response.send_message("まだ開始してない！", ephemeral=True)
            return

        start = datetime.datetime.fromisoformat(user["study_start"])
        minutes = int((datetime.datetime.now() - start).total_seconds() / 60)

        before = get_level(user["exp"])

        # ===== プレミアムEXP =====
        gain = minutes
        if user["is_premium"]:
            gain = int(gain * 1.5)

        user["exp"] += gain
        after = get_level(user["exp"])

        # ===== ストリーク =====
        today = str(datetime.date.today())
        yesterday = str(datetime.date.today() - datetime.timedelta(days=1))

        if user["last_study_date"] == yesterday:
            user["streak"] += 1
        elif user["last_study_date"] != today:
            user["streak"] = 1

        user["last_study_date"] = today

        # ===== 履歴 =====
        user["history"][today] = user["history"].get(today, 0) + minutes

        user["study_start"] = None
        save_data()

        msg = f"⏱ {minutes}分勉強！\n+{gain}EXP\n合計: {user['exp']}分 Lv:{after}\n🔥 {user['streak']}日連続"

        if after > before:
            msg += "\n🎉 レベルアップ！"

        await interaction.response.send_message(msg)

# ===== イベント =====
@bot.event
async def on_ready():
    print(f"ログイン: {bot.user}")

@bot.event
async def setup_hook():
    await bot.tree.sync()
    bot.loop.create_task(daily_reset())

# ===== コマンド =====
@bot.tree.command(name="panel")
async def panel(interaction: discord.Interaction):
    embed = discord.Embed(title="📚 勉強パネル", color=discord.Color.green())
    await interaction.response.send_message(embed=embed, view=StudyView())

@bot.tree.command(name="status")
async def status(interaction: discord.Interaction):
    user = get_user(str(interaction.user.id), interaction.guild.id)
    level = get_level(user["exp"])

    badge = "👑 " if user["is_premium"] else ""

    embed = discord.Embed(title="📊 ステータス", color=discord.Color.blue())
    embed.add_field(name="名前", value=f"{badge}{interaction.user.name}")
    embed.add_field(name="合計時間", value=f"{user['exp']}分")
    embed.add_field(name="レベル", value=f"Lv.{level}")
    embed.add_field(name="連続日数", value=f"{user['streak']}日")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rank")
async def rank(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    users = data["users"].get(gid, {})
    sorted_users = sorted(users.items(), key=lambda x: x[1]["exp"], reverse=True)

    embed = discord.Embed(title="🏆 ランキング", color=discord.Color.gold())

    for i, (uid, u) in enumerate(sorted_users[:10], 1):
        try:
            user = await bot.fetch_user(int(uid))
            name = user.name
        except:
            name = "Unknown"

        if u.get("is_premium"):
            name = "👑 " + name

        embed.add_field(name=f"{i}位 {name}", value=f"{u['exp']}分", inline=False)

    await interaction.response.send_message(embed=embed)

# ===== プレミアム管理 =====
@bot.tree.command(name="premium_add")
async def premium_add(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("権限なし", ephemeral=True)
        return

    user = get_user(str(member.id), interaction.guild.id)
    user["is_premium"] = True
    save_data()

    await interaction.response.send_message(f"{member.name} をプレミアムにしました 👑")

@bot.tree.command(name="premium_remove")
async def premium_remove(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("権限なし", ephemeral=True)
        return

    user = get_user(str(member.id), interaction.guild.id)
    user["is_premium"] = False
    save_data()

    await interaction.response.send_message(f"{member.name} のプレミアム解除")

# ===== Flask（24時間化） =====
from flask import Flask
import threading

app = Flask(__name__)

@app.route("/")
def home():
    return "OK"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run).start()

# ===== 自動リセット =====
async def daily_reset():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.datetime.now()

        if now.hour == 0 and now.minute < 5:
            data["users"] = {}
            save_data()
            print("ランキングリセット")

        await asyncio.sleep(60)

# ===== 起動 =====
bot.run(TOKEN)
