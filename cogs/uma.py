import discord
from discord.ext import commands, tasks
import logging
import requests

class Uma(commands.Cog, name='Uma'):
	def __init__(self, bot, *args, **kwargs):
		self.bot = bot
		self.logger = logging.getLogger(__name__)
		self.logger.setLevel(logging.INFO)

	@commands.command(aliases=['umabanner'])
	async def uma(self, ctx: commands.Context):
		"""Displays the current Umamusume banner information"""

		url = 'https://api.games.umamusume.com/umamusume/ajax/info_index?format=json'
		request = {'category':0, 'device':4, 'viewer_id':0, 'limit':10, 'offset':0}

		json = {}
		try:
			response = requests.post(url, json=request, timeout=5)
			if response.status != 200:
				await ctx.send('Failed to fetch banner information.')
				return
			json = response.json()
		except (requests.RequestException, requests.exceptions.JSONDecodeError) as e:
			await ctx.send('An error occurred while fetching banner information.')
			self.logger.error(f'Error fetching uma banner info: {e}')
			return

		infolist = json['information_list']
		if not infolist:
			await ctx.send('No banner information available.')
			return
		embeds = []
		for entry in infolist:
			title = f'**{entry['title'].replace('*', '\\*')}**'
			embed = discord.Embed(title=title)
			if entry['image']:
				embed.set_image(url=entry['image'])
			embeds.append(embed)
		await ctx.send(embeds=embeds)


async def setup(client):
	await client.add_cog(Uma(client))