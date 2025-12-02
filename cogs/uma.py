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

		url = 'https://umamusume.com/api/ajax/pr_info_index?format=json'
		request = {'announce_label':1, 'limit':10, 'offset':0}

		json = {}
		try:
			response = requests.post(url, json=request, timeout=4)
			if not response.ok:
				await ctx.send('Failed to fetch banner information.')
				return
			json = response.json()
		except (requests.RequestException, requests.exceptions.JSONDecodeError) as e:
			await ctx.send('An error occurred while fetching banner information.')
			self.logger.error(f'Error fetching uma banner info: {e}')
			return
		if not json['response_code'] or json['response_code'] != 1 or not json['information_list']:
			await ctx.send('Bad API response - No banner information available.')
			return
		embeds = []
		for entry in json['information_list']:
			title = f'**{entry['title'].replace('*', '\\*')}**'
			embed = discord.Embed(title=title)
			if entry['image']:
				embed.set_image(url=entry['image'])
			embeds.append(embed)
		await ctx.send(embeds=embeds)


async def setup(client):
	await client.add_cog(Uma(client))