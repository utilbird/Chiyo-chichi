import discord
from discord.ext import commands

def send_message(bot: commands.Bot, message, id: int, embed = None):
	"""Used to easily send messages from non-async callers"""
	channel = bot.get_channel(id)
	if not channel:
		return
	bot.loop.create_task(channel.send(message, embed=embed))