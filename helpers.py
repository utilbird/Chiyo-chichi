import discord
from discord.ext import commands
import re

def send_message(bot: commands.Bot, message, id: int, embed = None):
	"""Used to easily send messages from non-async callers"""
	channel = bot.get_channel(id)
	if not channel:
		return
	bot.loop.create_task(channel.send(message, embed=embed))

notag = re.compile(r'<.*?>')
def html_to_discord(html: str) -> str:
	"""Convert basic HTML tags to Discord markdown"""
	replacements = {
		'<b>': '**',
		'</b>': '**',
		'<strong>': '**',
		'</strong>': '**',
		'<i>': '*',
		'</i>': '*',
		'<em>': '*',
		'</em>': '*',
		'<u>': '__',
		'</u>': '__',
		'<br>': '\n',
		'<br/>': '\n',
		'<br />': '\n',
	}
	for html_tag, discord_md in replacements.items():
		html = html.replace(html_tag, discord_md)
	# Remove any remaining HTML tags
	html = re.sub(notag, '', html)
	return html