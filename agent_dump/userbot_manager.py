from asgiref.sync import sync_to_async
import os
import sys
import logging
import asyncio
import inspect
import threading
from telethon import TelegramClient, events
from django.contrib.auth import get_user_model
from chat.models import ChatMessage, Contact, Telegram
from agent_dump.agent_workflow import agent_generate_reply
from agent_dump.pipeline_utils import import_sample_chats_to_db, classify_new_messages, embed_new_messages, convert_dpo_feedback_to_sft
from datetime import datetime

User = get_user_model()

class TelegramUserBotManager:
    def __init__(self, user, api_id, api_hash, session_name, model_choice='kimi'):
        print(f"[UserBotManager] Initializing for user: {user.username}, model: {model_choice}")
        self.user = user
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.session_name = session_name
        self.model_choice = model_choice
        self.username = str(self.user.username)
        self.BASE_DIR = os.path.join('agent_dump', self.username)
        os.makedirs(self.BASE_DIR, exist_ok=True)
        self.client = None  # Will be created in the thread with event loop
        self.handler_attached = False
        self.running = False
        self.loop = None
        self.generate = None  # Will be set in start()
        # self._setup_handlers()  # Handlers will be set after client is created

    def _select_model(self):
        if self.model_choice == 'kimi':
            return agent_generate_reply
        else:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            # Use the actual dpo_model directory (no checkpoint subdir)
            EXTRACT_DIR = os.path.join(self.BASE_DIR, 'dpo_model')
            tokenizer = AutoTokenizer.from_pretrained(EXTRACT_DIR)
            model = AutoModelForCausalLM.from_pretrained(EXTRACT_DIR)
            def dpo_generate_reply(prompt: str, max_new_tokens: int = 60) -> str:
                inputs = tokenizer(prompt, return_tensors="pt")
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    repetition_penalty=1.2,
                    eos_token_id=tokenizer.eos_token_id if tokenizer.eos_token_id else None,
                )
                generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
                if generated_text.startswith(prompt):
                    response = generated_text[len(prompt):].strip()
                else:
                    response = generated_text.strip()
                sentences = __import__('re').split(r'(?<=[.!?])\s+', response)
                return ' '.join(sentences[:2]).strip()
            return dpo_generate_reply

    def _setup_handlers(self):
        if self.handler_attached:
            print(f"[UserBotManager] Handler already attached for {self.user.username}")
            return
        print(f"[UserBotManager] Attaching event handler for {self.user.username}")
        @self.client.on(events.NewMessage(incoming=True))
        async def handler(event):
            print(f"[UserBotManager] New incoming message event for {self.user.username}")
            try:
                sender = await event.get_sender()
                sender_id = getattr(sender, 'id', None)
                sender_username = getattr(sender, 'username', None)
                contact_name = sender_username or getattr(sender, 'first_name', None) or str(sender_id or "Unknown")
                user_message = event.raw_text or ""
                print(f"[UserBotManager] Message from {contact_name}: {user_message}")
                # Find or create Contact
                contact, created = await sync_to_async(Contact.objects.get_or_create)(user=self.user, name=contact_name, platform='Telegram')
                # Update telegram_user_id and telegram_username if changed
                updated = False
                if sender_id and (not contact.telegram_user_id or contact.telegram_user_id != sender_id):
                    contact.telegram_user_id = sender_id
                    updated = True
                if sender_username and (not contact.telegram_username or contact.telegram_username != sender_username):
                    contact.telegram_username = sender_username
                    updated = True
                if updated:
                    await sync_to_async(contact.save)()
                # Generate reply (but do not send yet)
                if self.model_choice == 'kimi':
                    if inspect.iscoroutinefunction(self.generate):
                        ai_reply = await self.generate(user_message, self.username)
                    else:
                        ai_reply = await asyncio.to_thread(self.generate, user_message, self.username)
                else:
                    if inspect.iscoroutinefunction(self.generate):
                        ai_reply = await self.generate(user_message)
                    else:
                        ai_reply = await asyncio.to_thread(self.generate, user_message)
                # Store message in DB, replied=False
                chat_msg = await sync_to_async(ChatMessage.objects.create)(
                    user=self.user,
                    contact=contact,
                    timestamp=datetime.now(),
                    message=user_message,
                    ai_generated_message=ai_reply,
                    user_approved_reply=False,
                    reply_sent=False,
                    platform='Telegram',
                    telegram_chat_id=getattr(event, 'chat_id', None),
                    telegram_message_id=getattr(event, 'id', None),
                )
                print(f"[UserBotManager] ChatMessage created in DB for {self.user.username}, id={chat_msg.id}")
            except Exception as e:
                print(f"[UserBotManager] Exception in handler for {self.user.username}: {e}")
        self.handler_attached = True

    def health_status(self):
        status = {
            'running': self.running,
            'client_created': self.client is not None,
            'handler_attached': self.handler_attached,
        }
        if self.client:
            status['connected'] = getattr(self.client, 'is_connected', lambda: False)()
        return status

    def start(self):
        if self.running:
            print(f"[UserBotManager] Userbot already running for {self.user.username}")
            return
        print(f"[UserBotManager] Starting userbot for {self.user.username}")
        self.running = True
        # Select model once at start
        self.generate = self._select_model()

        def _run():
            print(f"[UserBotManager] Thread started for {self.user.username}")
            asyncio.run(self._start_with_pin_handling())
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self.thread = t

    async def _start_with_pin_handling(self):
        telegram_obj = await sync_to_async(Telegram.objects.get)(user=self.user)
        print(f"[UserBotManager] _start_with_pin_handling for {self.user.username}")
        # Create TelegramClient in this thread/event loop
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        self._setup_handlers()  # Now safe to set handlers (will only attach once)
        # Try to connect and handle PIN if needed
        try:
            await self.client.connect()
            print(f"[UserBotManager] Connected to Telegram for {self.user.username}")
            if not await self.client.is_user_authorized():
                print(f"[UserBotManager] Not authorized, starting authentication for {self.user.username}")
                # Start authentication
                phone = telegram_obj.telegram_mobile_number
                await self.client.send_code_request(phone)
                print(f"[UserBotManager] Code request sent to {phone}")
                # Check if PIN is required (2FA enabled)
                if telegram_obj.telegram_pin_code:
                    print(f"[UserBotManager] PIN already provided for {self.user.username}, trying to sign in")
                    # PIN already provided, try to sign in
                    try:
                        await self.client.sign_in(phone, telegram_obj.telegram_pin_code)
                        telegram_obj.pin_required = False
                        await sync_to_async(telegram_obj.save)()
                        print(f"[UserBotManager] Signed in successfully with PIN for {self.user.username}")
                    except Exception as e:
                        print(f"[UserBotManager] PIN incorrect or expired for {self.user.username}: {e}")
                        telegram_obj.pin_required = True
                        await sync_to_async(telegram_obj.save)()
                        return  # Wait for frontend to provide new PIN
                else:
                    print(f"[UserBotManager] PIN not provided for {self.user.username}, setting pin_required and waiting")
                    # PIN not provided, set pin_required and wait
                    telegram_obj.pin_required = True
                    await sync_to_async(telegram_obj.save)()
                    # Wait for frontend to provide PIN (poll DB)
                    while telegram_obj.pin_required:
                        print(f"[UserBotManager] Waiting for PIN for {self.user.username}...")
                        await asyncio.sleep(2)
                        await sync_to_async(telegram_obj.refresh_from_db)()
                    print(f"[UserBotManager] PIN received for {self.user.username}, trying to sign in")
                    # Try to sign in again with new PIN
                    try:
                        await self.client.sign_in(phone, telegram_obj.telegram_pin_code)
                        telegram_obj.pin_required = False
                        await sync_to_async(telegram_obj.save)()
                        print(f"[UserBotManager] Signed in successfully after PIN for {self.user.username}")
                    except Exception as e:
                        print(f"[UserBotManager] PIN incorrect after waiting for {self.user.username}: {e}")
                        telegram_obj.pin_required = True
                        await sync_to_async(telegram_obj.save)()
                        return
            else:
                print(f"[UserBotManager] Already authorized for {self.user.username}")
            # If authorized, start background reply sender
            print(f"[UserBotManager] Starting background reply sender for {self.user.username}")
            await self._background_reply_sender()
        except Exception as e:
            import logging
            print(f"[UserBotManager] Exception in _start_with_pin_handling for {self.user.username}: {e}")
            logging.exception(f"Userbot failed to start for {self.user.username}: {e}")
            telegram_obj.pin_required = True
            await sync_to_async(telegram_obj.save)()

    async def _background_reply_sender(self):
        print(f"[UserBotManager] Entered _background_reply_sender for {self.user.username}")
        # Ensure handler is attached (in case client was re-created)
        self._setup_handlers()
        async with self.client:
            # Start Telethon client in background
            client_task = asyncio.create_task(self.client.run_until_disconnected())
            while self.running:
                # Only send replies for messages user has approved and not yet sent
                pending = await sync_to_async(lambda: list(ChatMessage.objects.select_related('contact').filter(user=self.user, user_approved_reply=True, reply_sent=False, platform='Telegram')))()
                pending_count = len(pending)
                print(f"[UserBotManager] Pending messages to reply for {self.user.username}: {pending_count}")
                for msg in pending:
                    reply_text = msg.reply_message or msg.ai_generated_message
                    try:
                        if msg.telegram_chat_id and msg.telegram_message_id:
                            print(f"[UserBotManager] Sending reply to chat_id={msg.telegram_chat_id}, message_id={msg.telegram_message_id} for message {msg.id} by {self.user.username}")
                            await self.client.send_message(
                                entity=msg.telegram_chat_id,
                                message=reply_text,
                                reply_to=msg.telegram_message_id
                            )
                        else:
                            contact = msg.contact
                            peer = None
                            if contact.telegram_user_id:
                                peer = contact.telegram_user_id
                            elif contact.telegram_username:
                                peer = contact.telegram_username
                            else:
                                peer = None
                            if peer is None:
                                print(f"[UserBotManager] WARNING: No valid peer for message {msg.id} by {self.user.username}. Marking as sent and skipping.")
                                msg.reply_sent = True
                                await sync_to_async(msg.save)()
                                continue
                            print(f"[UserBotManager] Sending fallback reply to {peer} for message {msg.id} by {self.user.username}")
                            await self.client.send_message(peer, reply_text)
                        msg.reply_sent = True
                        await sync_to_async(msg.save)()
                        print(f"[UserBotManager] Reply sent and marked for message {msg.id} by {self.user.username}")
                        # Feedback pipeline (pass username)
                        asyncio.create_task(asyncio.to_thread(classify_new_messages))
                        asyncio.create_task(asyncio.to_thread(import_sample_chats_to_db, self.username))
                        asyncio.create_task(asyncio.to_thread(embed_new_messages))
                        feedback_csv = os.path.join(self.BASE_DIR, 'dpo_feedback_log.csv')
                        sft_jsonl = os.path.join(self.BASE_DIR, 'sft_dataset.jsonl')
                        asyncio.create_task(asyncio.to_thread(convert_dpo_feedback_to_sft, feedback_csv, sft_jsonl))
                    except Exception as e:
                        print(f"[UserBotManager] Failed to send reply for message {msg.id} by {self.user.username}: {e}")
                        logging.exception(f"Failed to send reply for message {msg.id}: {e}")
                await asyncio.sleep(2)  # Polling interval
            print(f"[UserBotManager] Exiting _background_reply_sender for {self.user.username}")
            await client_task

    def stop(self):
        print(f"[UserBotManager] Stopping userbot for {self.user.username}")
        if self.running:
            try:
                loop = asyncio.get_running_loop()
                coro = self.client.disconnect()
                if asyncio.iscoroutine(coro):
                    asyncio.create_task(coro)
                else:
                    coro
            except RuntimeError:
                # No running loop, so create one
                asyncio.run(self.client.disconnect())
            self.running = False
            print(f"[UserBotManager] Userbot stopped for {self.user.username}")
