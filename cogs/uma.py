import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup

class Uma(commands.Cog, name='Uma'):
	def __init__(self, bot, *args, **kwargs):
		self.bot = bot

	@commands.command(aliases=['umabanner'])
	async def uma(self, ctx: commands.Context):
		"""Displays the current Umamusume banner information"""
		await ctx.send("WIP")
		"""
		url = 'https://gametora.com/umamusume/gacha/history'
		args = '?server=en&year=all&type=char'

		html = ''
		try:
			with requests.get(url + args) as response:
				if response.status != 200:
					await ctx.send("Failed to fetch banner information.")
					return
				html = response.text
		except:
			await ctx.send("An error occurred while fetching banner information.")
			return

		soup = BeautifulSoup(html, 'html.parser')
		banner = soup.find('div', class_='sc-37bc0b3c-0 cjSLqN') # Should find the first one, the current banner.
		if not banner:
			await ctx.send("No banner information found.")
			return

		banner_img = banner.find('img')['src']
		banner_title = ''
		for str in banner.find_all('span', class_='gacha_link_alt__mZW_P'):
			banner_title += f'{str.string.strip()}\n'
		banner_date = banner.find('span', class_='sc-37bc0b3c-2 cVFYc').get_text()

		embed = discord.Embed(title="Current Umamusume Banner", description=banner_title, color=discord.Color.blue())
		embed.set_image(url=banner_img)
		await ctx.send(embed=embed)
		"""


async def setup(client):
	await client.add_cog(Uma(client))