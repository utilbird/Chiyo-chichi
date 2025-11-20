import discord
import random
from discord.ext import commands

class Randfun(commands.Cog, name='Random'):
	def __init__(self, bot, *args, **kwargs):
		self.bot = bot

	@commands.command(aliases=['spin', 'wheelspin'])
	async def wheel(self, ctx: commands.Context):
		"""Picks a random user from voice channel participants or arguments"""
		selected = None
		if ctx.message.mentions:
			selected = random.choice(ctx.message.mentions)
		elif ctx.message.author.voice and ctx.message.author.voice.channel:
			selected = random.choice(ctx.message.author.voice.channel.members)
		elif ctx.message.mention_everyone or 'everyone' in ctx.message.content:
			selected = random.choice(ctx.channel.members)
		else:
			return await ctx.send('Invalid command usage. Must mention users in command argument or be in a voice channel.')
		if selected is None:
			return await ctx.send('Error. No valid users found, contact dev.')
		await ctx.send(f'<@{selected.id}>')

	@commands.command(aliases=['flip', 'coin'])
	async def coinflip(self, ctx: commands.Context):
		"""Flip a coin"""
		outcomes = [':flushed:\nHeads', ':snake:\nTails', 'Woah - It landed completely upright!?']
		probs = [49.95, 49.95, 0.1]
		await ctx.send(random.choices(outcomes, probs, k=1)[0])

async def setup(client):
	await client.add_cog(Randfun(client))