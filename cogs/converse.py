import discord
from discord.ext import commands
import datetime
import os.path
import random
import logging

class Converse(commands.Cog):
	clog_next_record = {}
	clog_next_response = {}

	conversation_log_interval: datetime.timedelta # Minimum time between logging a message for conversation
	conversation_response_interval: datetime.timedelta # Minimum time between conversation responses

	def __init__(self, bot, *args, **kwargs):
		self.bot = bot
		self.logger = logging.getLogger(__name__)
		self.logger.setLevel(logging.INFO)
		self.conversation_log_interval = datetime.timedelta(seconds=bot.config['conversation_log_interval'])
		self.conversation_response_interval = datetime.timedelta(seconds=bot.config['conversation_response_interval'])
	
	def conversation_catalog(self, message: discord.Message, force: bool = False):
		"""Record messages ocassionally to randomly respond with"""
		now = datetime.datetime.now()
		if force or message.guild.id not in self.clog_next_record or self.clog_next_record[message.guild.id] < now:
			if self.bot.user in message.mentions:
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
			self.clog_next_record[message.guild.id] = now + self.conversation_log_interval

	def conversation_response(self, message: discord.Message) -> str | None:
		"""Chance to respond to this message with a random message (return value)"""
		res_chance = self.bot.config['conversation_response_chance']
		now = datetime.datetime.now()
		if message.guild.id not in self.clog_next_response or self.clog_next_response[message.guild.id] < now or self.bot.user in message.mentions:
			if (random.random() <= res_chance or self.bot.user in message.mentions) and os.path.exists('store/conversation.txt'):
				self.clog_next_response[message.guild.id] = now + self.conversation_response_interval
				with open('store/conversation.txt', 'r', encoding='utf-8') as f:
					return random.choice(f.readlines()).replace('\\n', '\n')

	@commands.Cog.listener()
	async def on_message(self, message: discord.Message):
		if message.author.id == self.bot.user.id:
			return
		if not message.content or message.content[0] == '!':
			return
		self.conversation_catalog(message)
		response = self.conversation_response(message)
		if response:
			await message.channel.send(response)\

async def setup(client):
	await client.add_cog(Converse(client))