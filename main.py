import os
import sys
import json
import discord
import logging
import datetime
import requests
import re
import random
import schedule
import pytz
import lavalink
from discord.ext import commands, tasks
import helpers

if not os.path.isdir('store'):
	os.mkdir('store')

log = logging.getLogger(__name__)

config = {}
with open('store/config.json', 'r') as f:
	config = json.load(f)

# Courtesy of https://stackoverflow.com/a/51916936
tdregex = re.compile(r'^((?P<days>[\.\d]+?)d)?((?P<hours>[\.\d]+?)h)?((?P<minutes>[\.\d]+?)m)?((?P<seconds>[\.\d]+?)s)?$')

reminders = {}

timezone = pytz.timezone(config['timezone'])
conversation_log_interval = datetime.timedelta(seconds=config['conversation_log_interval']) # Minimum time between logging a message for conversation
conversation_response_interval = datetime.timedelta(seconds=config['conversation_response_interval']) # Minimum time between conversation responses

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.members =  True
intents.guilds = True
intents.voice_states = True
intents.guild_messages = True
intents.guild_reactions = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=commands.DefaultHelpCommand(width = 100, no_category='Commands'))
bot.config = config

### METHODS ###

clog_next_record = {}
def conversation_catalog(message: discord.Message, force: bool = False):
	"""Record messages ocassionally to randomly respond with"""
	now = datetime.datetime.now()
	if force or message.guild.id not in clog_next_record or clog_next_record[message.guild.id] < now:
		if bot.user in message.mentions:
			return
		# uncomment if gay
		#if message.mention_everyone:
		#	return
		msg = ''
		if len(message.content) != 0 and len(message.content) < 200:
			msg = message.content
		elif message.attachments and message.attachments[0].content_type and (message.attachments[0].content_type.startswith('image/') or message.attachments[0].content_type.startswith('video/')) and message.attachments[0].url:
			msg = message.attachments[0].url
		elif message.embeds and message.embeds[0].url:
			msg = message.embeds[0].url
		else:
			return
		with open('store/conversation.txt', 'a', encoding="utf-8") as f:
			f.write(msg.replace('\n','\\n'))
			f.write('\n')
		clog_next_record[message.guild.id] = now + conversation_log_interval

res_chance = config['conversation_response_chance']
clog_next_response = {}
def conversation_response(message: discord.Message) -> str | None:
	"""Chance to respond to this message with a random message (return value)"""
	now = datetime.datetime.now()
	if message.guild.id not in clog_next_response or clog_next_response[message.guild.id] < now or bot.user in message.mentions:
		if (random.random() <= res_chance or bot.user in message.mentions) and os.path.exists('store/conversation.txt'):
			clog_next_response[message.guild.id] = now + conversation_response_interval
			with open('store/conversation.txt', 'r', encoding='utf-8') as f:
				return random.choice(f.readlines()).replace('\\n', '\n')

def remind(memberID: int, channelID: int, message):
	helpers.send_message(f'<@{memberID}> {message}', channelID)
	return schedule.CancelJob()

def add_reminder(memberID: int, channelID: int, message, td: datetime.timedelta):
	schedule.every(int(td.total_seconds())).seconds.do(remind, memberID, channelID, message)

def graceful_shutdown():
	lb = bot.get_cog('Leaderboard')
	if lb is not None:
		lb.on_shutdown()
	schedule.clear()

def restart_bot(channel: discord.TextChannel = None):
	log.info('Restarting...')
	graceful_shutdown()
	update_cmd = 'git pull'
	if channel:
		with open('store/update.log', 'w') as f:
			f.write(str(channel.id))
			f.write('\n')
		update_cmd += ' >> store/update.log'
	if os.system(update_cmd) != 0:
		return
	python = sys.executable
	quit(0) # combine with systemd 'Restart=on-success'
	# comment above and uncomment below if not using a service manager
	#os.execv(python, [python] + sys.argv)

def get_aurora_status() -> discord.Embed | None:
	tzinfo = datetime.datetime.now().astimezone().tzinfo
	api = 'https://sws-data.sws.bom.gov.au/api/v1/get-aurora-alert'
	time_format = '%Y-%m-%d %H:%M:%S'
	try:
		response = requests.post(api, json={'api_key': config['bom_spaceweather_apikey']})
		response.raise_for_status()
		data = response.json()['data']
		desc = ''
		i = 0
		if len(data) == 0:
			desc = 'No active alerts.'
		else:
			for alert in data:
				i += 1
				start_time = datetime.datetime.strptime(alert['start_time'], time_format)
				desc += f'\tStart time: {start_time.astimezone(tzinfo)}\n'
				valid_until = datetime.datetime.strptime(alert['valid_until'], time_format)
				desc += f'\tValid until: {valid_until.astimezone(tzinfo)}\n'
				desc += f'\tAlert level: {alert['k_aus']}\n'
				desc += f'\tLatitude band: {alert['lat_band']}\n'
				desc += f'\tDescription: {alert['description'].replace('\n', '\n\t')}\n'
				if i < len(data):
					desc += '\n\n'

		embed = discord.Embed(title='Aurora Alert', description=desc)
		embed.set_footer(text='Information provided by sws-data.sws.bom.gov.au')
		return embed
	except requests.HTTPError as e:
		log.error(f'HTTP error occured while fetching aurora status.\n{e}')
		try:
			rjson = response.json()
			if 'errors' in rjson:
				log.error(rjson['errors'])
		except requests.exceptions.JSONDecodeError:
			pass
	except requests.ConnectionError as e:
		log.error(f'Connection error while fetching aurora status.\n{e}')
	except requests.RequestException as e:
		log.error(f'Request exception occured while fetching aurora status.\n{e}')
	except requests.Timeout:
		log.error(f'Timeout occured while fetching aurora status.')
	except requests.exceptions.JSONDecodeError as e:
		log.error(f'Unable to decode JSON from aurora status response.\n{e}')

	

### BOT EVENTS ###
#@bot.event
#async def on_voice_state_update(self, member, before, after):
#	# lavalink
#	if member.id == self.bot.user.id and before.channel and not after.channel:
#		# Bot was disconnected from voice
#		player = self.bot.lavalink.get_player(member.guild.id)
#		if player:
#			await player.destroy()

@bot.event
async def on_ready():
	log.info(f'Logged in as {bot.user}')
	if os.path.exists('store/update.log'):
		try: 
			with open('store/update.log', 'r') as f:
				channel = bot.get_channel(int(f.readline()))
				await channel.send(f'```{'\n'.join(f.readlines())}```')
		except Exception as e:
			log.error(e)
		finally:
			os.remove('store/update.log')
	for file in os.listdir('cogs'):
		await bot.load_extension(f'cogs.{file[:-3]}')
	if config['lavalink_enable'] and not hasattr(bot, 'lavalink'):
		bot.lavalink = lavalink.Client(bot.user.id)
		bot.lavalink.add_node(config['lavalink_host'],
						config['lavalink_port'],
						config['lavalink_password'],
						config['lavalink_region'],
						config['lavalink_name'])

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
		await message.channel.send(response)

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
		return await ctx.send('Invalid command usage. Must mention users in command argument or be in a voice channel.')
	if selected is None:
		return await ctx.send('Error. No valid users found, contact dev.')
	await ctx.send(f'<@{selected.id}>')

@bot.command(aliases=['flip', 'coin'])
async def coinflip(ctx: commands.Context):
	"""Flip a coin"""
	outcomes = [':flushed:\nHeads', ':snake:\nTails', 'Woah - It landed completely upright!?']
	probs = [49.95, 49.95, 0.1]
	await ctx.send(random.choices(outcomes, probs, k=1)[0])
	
@bot.command()
async def catchup(ctx: commands.Context, limit = 5000):
	"""Goes through previous channel history to update quote DB. argument specifies how far to look back (default=5000)"""
	if ctx.author.guild_permissions.administrator == False:
		return await ctx.send('Insufficient permissions')
	await ctx.send('Gathering quotes...')
	async for msg in ctx.channel.history(limit=limit):
		conversation_catalog(msg, True)
	await ctx.send(f'Finished. Gathered ~{limit} quotes.')\

@bot.command()
async def update(ctx: commands.Context):
	"""Updates bot from github"""
	if ctx.author.id != config['dev_user_id']:
		return await ctx.send('no')
	rmsg = 'Updating and restarting process...'
	if(config['restart_special_message']):
		rmsg += f'\n{config['restart_special_message']}'
	await ctx.send(rmsg)
	restart_bot(ctx.channel)
	await ctx.send('Update failed.')

@bot.command()
async def remind(ctx: commands.Context, message):
	substrs = tdregex.match(message)
	if not substrs:
		return await ctx.send('Invalid format. Examples of valid formats: *2d* / *1d6h20m* / *30m20s*')
	param_dict = {name: float(param)
				for name, param in substrs.groupdict().items() if param}
	td = datetime.timedelta(**param_dict)
	add_reminder(td)
	await ctx.send('ok :)')

@bot.command()
async def play(ctx: commands.Context, *, query):
	"""Play music via link/search query"""
	if not config['lavalink_enable']:
		return await ctx.send('Music not enabled in configuration')
	player = bot.lavalink.get_player(ctx.guild.id)
	if player is None:
		return await ctx.send('Music player not initialized')
	if not player.is_connected:
		if not ctx.author.voice:
			return await ctx.send("You are not in a voice channel")
		channel = ctx.author.voice.channel
		await channel.connect(cls=lavalink.discord.VoiceClient)
		player.store('channel', channel.id)
	elif player.channel_id == ctx.channel.id:
		player.move_to(ctx.author.voice.channel.id)
	results = await player.search(query, ctx.author)
	if not results or not results.tracks:
		return await ctx.send("No results found.")
	track = results.tracks[0]
	player.add(requester=ctx.author.id, track=track)
	channel.store('requester_id', ctx.author.id)
	if not player.is_playing:
		await player.play()
		await ctx.send(f"Now playing: {track.title}")
	else:
		await ctx.send(f"Added to queue: {track.title}")

@bot.command()
async def weather(ctx: commands.Context, message):
	"""Gets the weather for a certain area"""
	await ctx.send('Feature not yet implemented.')
	return

@bot.command(aliases=['aurora', 'magstorm', 'sweather'])
async def spaceweather(ctx: commands.Context):
	res = get_aurora_status()
	if res is None:
		await ctx.send('Error occurred, sorry :(')
		return
	await ctx.send(embed=res)

@tasks.loop(hours=12)
async def weatherupdate():
	return

bot.run(config['token'])