import discord
from discord.ext import commands, tasks
import logging
import requests
import os
import json
import helpers

class Uma(commands.Cog, name='Uma'):

	url = 'https://umamusume.com/api/ajax/pr_info_index?format=json'

	def __init__(self, bot, *args, **kwargs):
		self.bot = bot
		self.logger = logging.getLogger(__name__)
		self.logger.setLevel(logging.INFO)
		if not os.path.exists('store/uma.json'):
			with open('store/uma.json', 'w') as f:
				json.dump({}, f)

	def remember_news(self, serverID: str, news_id: str):
		"""Remember that we've seen this news ID"""
		jdata = {}
		try:
			with open('store/uma.json', 'r') as f:
				jdata = json.load(f)
		except (FileNotFoundError, json.JSONDecodeError):
			jdata = {}
		if serverID not in jdata:
			jdata[serverID] = {}
		jdata[serverID]['last_news_id'] = news_id
		with open('store/uma.json', 'w') as f:
			json.dump(jdata, f)
	
	def has_seen_news(self, serverID: str, news_id: str) -> bool:
		"""Check if we've seen this news ID before"""
		jdata = {}
		try:
			with open('store/uma.json', 'r') as f:
				jdata = json.load(f)
		except (FileNotFoundError, json.JSONDecodeError):
			return False
		if serverID not in jdata:
			return False
		return jdata[serverID]['last_news_id'] == news_id

	@commands.command(aliases=['umabanner'])
	async def uma(self, ctx: commands.Context, arg: str = ''):
		"""Displays the current Umamusume news. Use 'all' to see all recent news."""

		request = {'announce_label':1, 'limit':10, 'offset':0}

		json = {}
		try:
			response = requests.post(self.url, json=request, timeout=4)
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
		total_embed_chars = 0
		segmented = False
		for entry in json['information_list']:
			# check if we've seen this news before
			if arg.lower() != 'all' and self.has_seen_news(str(ctx.guild.id), str(entry['announce_id'])):
				break
			title = f'**{entry['title'].replace('*', '\\*')}**'
			if len(title) > 256:
				title = title[:253] + '...'
			message = ''
			if entry['message']:
				message = helpers.html_to_discord(entry['message'])
				if len(message) > 4090:
					message = message[:4090] + '...'
			embed = discord.Embed(title=title, description=message)
			if entry['image']:
				embed.set_image(url=entry['image'])
			footer = 'No date provided.'
			if entry['post_at']:
				footer = f'Announced: {entry['post_at']}'
			embed.set_footer(text=footer)
			# total embed length limit is 6000 characters
			total_embed_chars += len(title) + len(message) + len(footer)
			if total_embed_chars > 6000:
				await ctx.send(embeds=embeds)
				embeds = []
				total_embed_chars = 0
				segmented = True
			else:
				embeds.append(embed)
		if len(embeds) > 0:
			await ctx.send(embeds=embeds)
		elif not segmented:
			if arg.lower() == 'all':
				await ctx.send('No announcements found.')
			else:
				await ctx.send('No new announcements.')
		if len(json['information_list']) > 0:
			self.remember_news(str(ctx.guild.id), str(json['information_list'][0]['announce_id']))


async def setup(client):
	await client.add_cog(Uma(client))