import discord
from discord.ext import commands, tasks
import helpers
import datetime
import json
import logging

class Leaderboard(commands.Cog, name='Leaderboard'):
	# Tracking user vc join/leave times
	vc_timelog = {}
	# last time leaderboard was updated
	last_lb_update = None
	def __init__(self, bot, *args, **kwargs):
		self.bot = bot
		self.logger = logging.getLogger(__name__)
		self.logger.setLevel(logging.INFO)
		self.check_leaderboard_reset.start()
		
	
	def initialize_leaderboard(self, guild: discord.Guild) -> dict:
		announce_channel = 0
		for channel in guild.text_channels:
			if channel.name.lower() == 'general':
				announce_channel = channel.id
		return {'current': {}, 'top': {}, 'total': {}, 'lb_announce_channel': str(announce_channel)}

	def add_leaderboard_time(self, member: discord.Member, duration: datetime.timedelta):
		jdata = {}
		try:
			with open('store/leaderboard.json', 'r') as f:
				jdata = json.load(f)
		except FileNotFoundError:
			jdata = {}
		except json.JSONDecodeError as e:
			self.logger.warning(f'ALERT: JSON decode error for leaderboard.json, {e}', exc_info=True)
			jdata = {}
		guild_id = str(member.guild.id)
		if guild_id not in jdata:
			jdata[guild_id] = self.initialize_leaderboard(member.guild)
		member_id = str(member.id)
		for category in ['current', 'total']:
			if member_id not in jdata[guild_id][category]:
				jdata[guild_id][category][member_id] = 0
			jdata[guild_id][category][member_id] += int(duration.total_seconds())

		with open('store/leaderboard.json', 'w') as f:
			json.dump(jdata, f, indent=4)

	def get_leaderboard(self, guild: discord.Guild, category: str):
		"""Returns a dictionary of members and their VC time"""
		jdata = {}
		guild_id = str(guild.id)
		try:
			with open('store/leaderboard.json', 'r') as f:
				jdata = json.load(f)
		except FileNotFoundError:
			self.logger.warning('ALERT: leaderboard file not found')
			return
		except json.JSONDecodeError as e:
			self.logger.warning(f'ALERT: JSON decode error for leaderboard.json, {e}', exc_info=True)
			return
		if guild_id not in jdata:
			return
		lb = jdata[guild_id][category]
		if lb is not None:
			return sorted(lb.items(), key=lambda item: item[1], reverse=True)
	
	def set_leaderboard_channel(self, guild: discord.Guild, channel: discord.TextChannel) -> str:
		jdata = {}
		guild_id = str(guild.id)
		try:
			with open('store/leaderboard.json', 'r') as f:
				jdata = json.load(f)
		except FileNotFoundError:
			jdata = {guild_id: self.initialize_leaderboard(guild)}
		except json.JSONDecodeError as e:
			self.logger.warning(f'ALERT: JSON decode error for leaderboard.json, {e}', exc_info=True)
			return 'JSON decode error. Contact developer'
		if guild_id not in jdata:
			jdata[guild_id] = self.initialize_leaderboard(guild)
		jdata[guild_id]['lb_announce_channel'] = str(channel.id)

		with open('store/leaderboard.json', 'w') as f:
			json.dump(jdata, f, indent=4)
		return 'Success'
	
	def leaderboard_begin_track(self, member: discord.Member):
		guild_id = member.guild.id
		if guild_id not in self.vc_timelog:
			self.vc_timelog[guild_id] = {}
		self.vc_timelog[guild_id][member.id] = datetime.datetime.now()
	
	def update_leaderboard(self, member: discord.Member, remove: bool) -> datetime.timedelta | None:
		guild_id = member.guild.id
		if guild_id not in self.vc_timelog or member.id not in self.vc_timelog[guild_id]:
			self.logger.info(f'{member.display_name} left a voice channel (or had lb status updated), but join time not found (bot might have restarted).')
			return
		join_time = self.vc_timelog[guild_id].pop(member.id)
		duration = datetime.datetime.now() - join_time
		self.add_leaderboard_time(member, duration)
		if not remove:
			self.leaderboard_begin_track(member)
		return duration
	
	def get_leaderboard_embed(self, guild: discord.Guild, category: str) -> discord.Embed | None:
		"""Returns a formatted discord embed of a certain leaderboard category"""
		timezone = self.bot.config['timezone']

		desc = ''
		pretitle = ''
		footer = ''
		category = str.lower(category).replace(' ', '')
		match category:
			case 'current' | 'weekly':
				pretitle = 'Weekly'
				footer = f'Resets 12AM Monday morning ({timezone}).'
			case 'top' | 'record':
				pretitle = 'Highest Weekly'
				footer = f'Updates 12AM Monday morning ({timezone}).'
			case 'total' | 'alltime':
				pretitle = 'Total'
				footer = 'Total time spent in VC since this bot has joined.'
			case _:
				return
		lb = self.get_leaderboard(guild, category)
		i = 0
		if lb is not None:
			for entry in lb:
				if entry[1] == 0:
					continue
				i += 1
				user = self.bot.get_user(int(entry[0]))
				duration = datetime.timedelta(seconds=entry[1])
				desc += f'**{i}.**\t\t{user.display_name} - {duration}\n'
			if len(desc) == 0:
				desc = 'No recorded activity.'
		else:
			desc = 'No recorded activity.'
		embed = discord.Embed(title=f'{pretitle} VC Activity', description=desc)
		embed.set_footer(text=footer)
		return embed
	
	def reset_weekly_leaderboard(self):
		"""Updates the 'personal best' (aka 'top') section on the leaderboard and resets the weekly leaderboard"""
		self.logger.info('Resetting weekly leaderboard...')
		jdata = {}
		try:
			with open('store/leaderboard.json', 'r') as f:
				jdata = json.load(f)
		except FileNotFoundError:
			self.logger.warning('ALERT: leaderboard file not found')
			return
		except json.JSONDecodeError as e:
			self.logger.warning(f'ALERT: JSON decode error for leaderboard.json, {e}', exc_info=True)
			return
		for guild_id in jdata:
			channelID = int(jdata[guild_id]['lb_announce_channel'])
			if channelID != 0:
				guild = self.bot.get_guild(int(guild_id))
				embed = self.get_leaderboard_embed(guild, 'current')
				channelID = int(jdata[guild_id]['lb_announce_channel'])
				if embed:
					helpers.send_message(None, channelID, embed=embed)
			for member in jdata[guild_id]['current']:
				# if we're not in the 'top' leaderboard, add our score. Otherwise we only replace it if this week has a higher score
				if member not in jdata[guild_id]['top'] or jdata[guild_id]['current'][member] > jdata[guild_id]['top'][member]:
					jdata[guild_id]['top'][member] = jdata[guild_id]['current'][member]
				jdata[guild_id]['current'][member] = 0
		with open('store/leaderboard.json', 'w') as f:
			json.dump(jdata, f, indent=4)

	def on_shutdown(self):
		for guild_id in self.vc_timelog:
			member_id_list = list(self.vc_timelog[guild_id].keys())
			for member_id in member_id_list:
				member = self.bot.get_guild(guild_id).get_member(member_id)
				if member:
					self.update_leaderboard(member, True)
	
	@commands.Cog.listener()
	async def on_ready(self):
		for guild in self.bot.guilds:
			for vc in guild.voice_channels:
				for member in vc.members:
					self.leaderboard_begin_track(member)

	@commands.Cog.listener()
	async def on_voice_state_update(self, member, before, after):
		# leaderboard
		guild_id = member.guild.id
		user_id = member.id

		# User joined a voice channel
		if before.channel is None and after.channel is not None:
			self.leaderboard_begin_track(member)
			print(f'{member.display_name} joined {after.channel.name} at {self.vc_timelog[guild_id][user_id]}')

		# User left a voice channel
		elif before.channel is not None and after.channel is None:
			self.update_leaderboard(member, True)
			print(f'{member.display_name} left {before.channel.name}')
	
	@commands.command()
	async def leaderboard(self, ctx: commands.Context, category: str = 'current'):
		"""Displays voice channel activity rankings"""
		if ctx.guild.id in self.vc_timelog and self.vc_timelog[ctx.guild.id]:
			member_id_list = list(self.vc_timelog[ctx.guild.id].keys())
			for member_id in member_id_list:
				member = ctx.guild.get_member(member_id)
				if member:
					self.update_leaderboard(member, False)
		embed = self.get_leaderboard_embed(ctx.guild, category)
		if embed:
			await ctx.send(embed=embed)
		else:
			await ctx.send('Unknown category. Choose from current|top|total.')
	
	@commands.command()
	async def lbchannel(self, ctx: commands.Context, channel: discord.TextChannel):
		"""Set weekly VC activity leaderboard report channel"""
		if ctx.author.guild_permissions.manage_channels == False:
			return await ctx.send('Insufficient permissions.')
		msg = self.set_leaderboard_channel(ctx.guild, channel)
		await ctx.send(msg)
	
	@tasks.loop(seconds=60)
	async def check_leaderboard_reset(self):
		now = datetime.datetime.now().astimezone()
		if now.hour == 0 and now.minute < 2 and now.strftime('%A') == "Monday":
			# There's definately a better way to do this, but this is quick and handles timezone shifts. 3800 is arbitrary, just needs to be between 3600 and less than 604800.
			if self.last_lb_update is None or (now - self.last_lb_update).seconds > 3800:
				self.reset_weekly_leaderboard()
				self.last_lb_update = now

async def setup(client):
	await client.add_cog(Leaderboard(client))