import os
import sys
import json
import discord
import datetime
import random
import schedule
import pytz
from discord.ext import commands

if not os.path.isdir('store'):
	os.mkdir('store')

# Tracking user vc join/leave times
vc_timelog = {}

TOKEN = ''
with open('store/token.txt', 'r') as f:
	TOKEN = f.readline()
timezone = pytz.timezone('Australia/Melbourne')
conversation_log_interval = datetime.timedelta(seconds=15) # Minimum time between logging a message for conversation
conversation_response_interval = datetime.timedelta(seconds=240) # Minimum time between conversation responses
conversation_response_chance = 0.2 # Chance to respond per message after response cooldown (0-1)

intents = discord.Intents.default()
intents.message_content = True
intents.members =  True
intents.guilds = True
intents.voice_states = True
intents.guild_messages = True
intents.guild_reactions = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=commands.DefaultHelpCommand(no_category='Commands'))

### METHODS ###
def restart_bot():
	print('Restarting...')
	os.system('git pull')
	python = sys.executable
	os.execv(python, [python] + sys.argv)

def initialize_leaderboard(guild: discord.Guild) -> dict:
	announce_channel = 0
	for channel in guild.text_channels:
		if channel.name.lower() == 'general':
			announce_channel = channel.id
	return {'current': {}, 'top': {}, 'total': {}, 'lb_announce_channel': str(announce_channel)}

def add_leaderboard_time(member: discord.Member, duration: datetime.timedelta):
	jdata = {}
	try:
		with open('store/leaderboard.json', 'r') as f:
			jdata = json.load(f)
	except FileNotFoundError:
		jdata = {}
	except json.JSONDecodeError as e:
		print('ALERT: JSON decode error for leaderboard.json')
		print(e)
		jdata = {}
	guild_id = str(member.guild.id)
	if guild_id not in jdata:
		jdata[guild_id] = initialize_leaderboard(member.guild)
	member_id = str(member.id)
	for category in ['current', 'total']:
		if member_id not in jdata[guild_id][category]:
			jdata[guild_id][category][member_id] = 0
		jdata[guild_id][category][member_id] += int(duration.seconds)
	
	with open('store/leaderboard.json', 'w') as f:
		json.dump(jdata, f, indent=4)

def get_leaderboard(guild: discord.Guild, category: str):
	"""Returns a dictionary of members and their VC time"""
	jdata = {}
	guild_id = str(guild.id)
	try:
		with open('store/leaderboard.json', 'r') as f:
			jdata = json.load(f)
	except FileNotFoundError:
		print('ALERT: leaderboard file not found')
		return
	except json.JSONDecodeError as e:
		print('ALERT: JSON decode error for leaderboard.json')
		print(e)
		return
	if guild_id not in jdata:
		return
	lb = jdata[guild_id][category]
	if lb is not None:
		return sorted(lb.items(), key=lambda item: item[1], reverse=True)

def get_leaderboard_embed(guild: discord.Guild, category: str) -> discord.Embed | None:
	desc = ''
	pretitle = ''
	footer = ''
	category = str.lower(category)
	match category:
		case 'current':
			pretitle = 'Weekly'
			footer = f'Resets 12AM Monday morning ({timezone}).'
		case 'top':
			pretitle = 'Highest Weekly'
			footer = f'Updates 12AM Monday morning ({timezone}).'
		case 'total':
			pretitle = 'Total'
			footer = 'Total time spent in VC since this bot has joined.'
		case _:
			return
	lb = get_leaderboard(guild, category)
	i = 0
	if lb is not None:
		for entry in lb:
			if entry[1] == 0:
				continue
			i += 1
			user = bot.get_user(int(entry[0]))
			duration = datetime.timedelta(seconds=entry[1])
			desc += f'**{i}.**\t\t{user.display_name} - {duration}\n'
		if len(desc) == 0:
			desc = 'No recorded activity.'
	else:
		desc = 'No recorded activity.'
	embed = discord.Embed(title=f'{pretitle} VC Activity', description=desc)
	embed.set_footer(text=footer)
	return embed
	
def set_leaderboard_channel(guild: discord.Guild, channel: discord.TextChannel) -> str:
	jdata = {}
	guild_id = str(guild.id)
	try:
		with open('store/leaderboard.json', 'r') as f:
			jdata = json.load(f)
	except FileNotFoundError:
		jdata = {guild_id: initialize_leaderboard(guild)}
	except json.JSONDecodeError as e:
		print('ALERT: JSON decode error for leaderboard.json')
		print(e)
		return 'JSON decode error. Contact developer'
	if guild_id not in jdata:
		jdata[guild_id] = initialize_leaderboard(guild)
	jdata[guild_id]['lb_announce_channel'] = str(channel.id)

	with open('store/leaderboard.json', 'w') as f:
		json.dump(jdata, f, indent=4)
	return 'Success'

def reset_weekly_leaderboard():
	print('Resetting weekly leaderboard...')
	jdata = {}
	try:
		with open('store/leaderboard.json', 'r') as f:
			jdata = json.load(f)
	except FileNotFoundError:
		print('ALERT: leaderboard file not found')
		return
	except json.JSONDecodeError as e:
		print('ALERT: JSON decode error for leaderboard.json')
		print(e)
		return
	for guild_id in jdata:
		if int(jdata[guild_id]['lb_announce_channel']) != 0:
			guild = bot.get_guild(int(guild_id))
			embed = get_leaderboard_embed(guild, 'current')
			channel = guild.get_channel(int(jdata[guild_id]['lb_announce_channel']))
			if channel and embed:
				bot.loop.create_task(channel.send(embed=embed))
		for member in jdata[guild_id]['current']:
			if jdata[guild_id]['current'][member] > jdata[guild_id]['top'][member]:
				jdata[guild_id]['top'][member] = jdata[guild_id]['current'][member]
			jdata[guild_id]['current'][member] = 0
	with open('store/leaderboard.json', 'w') as f:
		json.dump(jdata, f, indent=4)

clog_next_record = {}
def conversation_catalog(message: discord.Message, force: bool = False):
	"""Record messages ocassionally to randomly respond with"""
	now = datetime.datetime.now()
	if force or message.guild.id not in clog_next_record or clog_next_record[message.guild.id] < now:
		if message.mention_everyone:
			return
		msg = ''
		if len(message.content) != 0 and len(message.content) < 200:
			msg = message.content
		elif message.attachments and message.attachments[0].content_type and message.attachments[0].content_type.startswith('image/') and message.attachments[0].url:
			msg = message.attachments[0].url
		elif message.embeds and message.embeds[0].url:
			msg = message.embeds[0].url
		else:
			return
		with open('store/conversation.txt', 'a', encoding="utf-8") as f:
			f.write(msg.replace('\n','\\n'))
			f.write('\n')
		clog_next_record[message.guild.id] = now + conversation_log_interval

clog_next_response = {}
def conversation_response(message: discord.Message) -> str | None:
	"""Chance to respond to this message with a random message (return value)"""
	now = datetime.datetime.now()
	if message.guild.id not in clog_next_response or clog_next_response[message.guild.id] < now:
		chance = conversation_response_chance
		if bot.user in message.mentions:
			chance = min(conversation_response_chance * 3, 1)
		if random.random() <= chance and os.path.exists('store/conversation.txt'):
			clog_next_response[message.guild.id] = now + conversation_response_interval
			with open('store/conversation.txt', 'r', encoding='utf-8') as f:
				return random.choice(f.readlines()).replace('\\n', '\n')


### BOT EVENTS ###



@bot.event
async def on_ready():
	schedule.every().monday.at('00:00', timezone).do(reset_weekly_leaderboard)
	print(f'Logged in as {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):
	guild_id = member.guild.id
	user_id = member.id

	# User joined a voice channel
	if before.channel is None and after.channel is not None:
		if guild_id not in vc_timelog:
			vc_timelog[guild_id] = {}
		vc_timelog[guild_id][user_id] = datetime.datetime.now()
		print(f'{member.display_name} joined {after.channel.name} at {vc_timelog[guild_id][user_id]}')

	# User left a voice channel
	elif before.channel is not None and after.channel is None:
		if guild_id in vc_timelog and user_id in vc_timelog[guild_id]:
			join_time = vc_timelog[guild_id].pop(user_id)
			duration = datetime.datetime.now() - join_time
			print(f'{member.display_name} left {before.channel.name}. Time spent: {duration}')
			add_leaderboard_time(member, duration)
		else:
			print(f'{member.display_name} left a voice channel, but join time not found (bot might have restarted).')

	# User switched voice channels
	#elif before.channel is not None and after.channel is not None and before.channel != after.channel:
	#	if guild_id in vc_timelog and user_id in vc_timelog[guild_id]:
	#		join_time = vc_timelog[guild_id].pop(user_id)
	#		duration = datetime.datetime.now() - join_time
	#		print(f'{member.display_name} switched from {before.channel.name} to {after.channel.name}. Time in old channel: {duration}')
	#	else:
	#		print(f'{member.display_name} switched channels, but join time not found (bot might have restarted).')
	#	
	#	# Record new join time for the new channel
	#	if guild_id not in vc_timelog:
	#		vc_timelog[guild_id] = {}
	#	vc_timelog[guild_id][user_id] = datetime.datetime.now()
	#	print(f'{member.display_name} joined {after.channel.name} at {vc_timelog[guild_id][user_id]}')
	

@bot.event
async def on_message(message: discord.Message):
	if(message.author.id == bot.user.id):
		return
	if(message.content and message.content[0] == '!'):
		await bot.process_commands(message)
		return
	conversation_catalog(message)
	response = conversation_response(message)
	if response:
		await message.channel.send(content=response)
	

@bot.command()
async def leaderboard(ctx: commands.Context, category: str = 'current'):
	"""Displays voice channel activity rankings"""
	embed = get_leaderboard_embed(ctx.guild, category)
	if embed:
		await ctx.send(embed=embed)
	else:
		await ctx.send(content='Unknown category. Choose from current|top|total.')

@bot.command()
async def lbchannel(ctx: commands.Context, channel: discord.TextChannel):
	"""Set weekly VC activity leaderboard report channel"""
	if ctx.author.guild_permissions.manage_channels == False:
		await ctx.send(content='Insufficient permissions.')
		return
	msg = set_leaderboard_channel(ctx.guild, channel)
	await ctx.send(content=msg)

@bot.command(aliases=['spin', 'wheelspin'])
async def wheel(ctx: commands.Context):
	"""Picks a random user from voice channel participants or arguments"""
	selected = None
	if ctx.message.mentions:
		selected = random.choice(ctx.message.mentions)
	elif ctx.message.author.voice and ctx.message.author.voice.channel:
		selected = random.choice(ctx.message.author.voice.channel.members)
	elif ctx.message.mention_everyone or 'everyone' in ctx.message.content:
		selected = random.choice(ctx.channel.members)
	else:
		await ctx.send(content='Invalid command usage. Must mention users in command argument or be in a voice channel.')
		return
	if selected is None:
		await ctx.send(content='Error. No valid users found, contact dev.')
		return
	await ctx.send(f'<@{selected.id}>')

@bot.command(aliases=['flip', 'coin'])
async def coinflip(ctx: commands.Context):
	"""Flip a coin"""
	outcomes = [':flushed:\nHeads', ':snake:\nTails', 'Woah - It landed completely upright!?']
	probs = [49.95, 49.95, 0.1]
	await ctx.send(content=random.choices(outcomes, probs, k=1)[0])
	
@bot.command()
async def catchup(ctx: commands.Context, limit = 5000):
	"""Goes through previous channel history to update quote DB. argument specifies how far to look back (default=5000)"""
	if ctx.author.guild_permissions.administrator == False:
		await ctx.send(content='Insufficient permissions')
		return
	await ctx.send(content='Gathering quotes...')
	async for msg in ctx.channel.history(limit=limit):
		conversation_catalog(msg, True)
	await ctx.send(content=f'Finished. Gathered ~{limit} quotes.')

bot.run(TOKEN)