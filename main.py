import os
import json
import discord
import datetime
import random
import schedule
import zoneinfo
from discord.ext import commands

if not os.path.isdir('store'):
	os.mkdir('store')

# Tracking user vc join/leave times
vc_timelog = {}

TOKEN = ''
with open('store/token.txt', 'r') as f:
	TOKEN = f.readline()
timezone = zoneinfo.ZoneInfo('Australia/Melbourne')

intents = discord.Intents.default()
intents.message_content = True
intents.members =  True
intents.guilds = True
intents.voice_states = True
intents.guild_messages = True
intents.guild_reactions = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=commands.DefaultHelpCommand(no_category='Commands'))

### METHODS ###

def add_leaderboard_time(member, duration: datetime.timedelta):
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
		jdata[guild_id] = {'current': {}, 'top': {}, 'total': {}}
	
	for category in ['current', 'total']:
		if member.id not in jdata[guild_id][category]:
			jdata[guild_id][category][str(member.id)] = 0
		jdata[guild_id][category][str(member.id)] += int(duration.seconds)
	
	with open('store/leaderboard.json', 'w') as f:
		json.dump(jdata, f, indent=4)

def get_leaderboard(guild, category):
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
	for guild in jdata:
		for member in jdata[guild]['current']:
			if jdata[guild]['current'][member] > jdata[guild]['top'][member]:
				jdata[guild]['top'][member] = jdata[guild]['current'][member]
			jdata[guild]['current'][member] = 0
	
### BOT EVENTS ###
@bot.event
async def on_ready():
	schedule.every().monday.at('00:00', timezone).do(reset_weekly_leaderboard)
	print(f'Logged in as {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):
	guild_id = str(member.guild.id)
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
	

#@bot.event
#async def on_message(message):
#	if(message.author == bot.user):
#		return

@bot.command()
async def leaderboard(ctx: commands.Context, category: str = 'current'):
	"""Displays voice channel activity rankings"""
	desc = ''
	i = 0
	pretitle = ''
	category = str.lower(category)
	match category:
		case 'current':
			pretitle = 'Weekly'
		case 'top':
			pretitle = 'Highest Weekly'
		case 'total':
			pretitle = 'Total'
		case _:
			await ctx.send(content='Unknown category. Choose from current|top|total.')
			return
	for entry in get_leaderboard(ctx.guild, category):
		if entry[1] == 0:
			continue
		i += 1
		user = bot.get_user(int(entry[0]))
		duration = datetime.timedelta(seconds=entry[1])
		desc += f'**{i}.**\t\t{user.display_name} - {duration}\n'
	if len(desc) == 0:
		desc = 'No recorded activity.'
	embed = discord.Embed(title=f'{pretitle} VC Activity', description=desc)

	await ctx.send(embed=embed)

@bot.command()
async def wheel(ctx: commands.Context):
	"""Picks a random user from voice channel participants or command arguments"""
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
	


bot.run(TOKEN)