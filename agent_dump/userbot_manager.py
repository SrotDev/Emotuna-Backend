
from asgiref.sync import sync_to_async
import logging
import asyncio
import inspect
import threading
from telethon import TelegramClient, events
from django.contrib.auth import get_user_model
from chat.models import ChatMessage, Contact, Telegram
from agent_dump.agent_workflow import agent_generate_reply
from agent_dump.pipeline_utils import classify_new_message, embed_new_message
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
        self.client = None  # Will be created in the thread with event loop
        self.handler_attached = False
        self.running = False
        self.loop = None
        self.generate = None  # Will be set in start()
        # self._setup_handlers()  # Handlers will be set after client is created

    def _select_model(self):
        # Always use kimi model regardless of user choice
        return agent_generate_reply

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
                # Always use kimi model
                try:
                    if inspect.iscoroutinefunction(self.generate):
                        ai_reply = await self.generate(user_message, self.username)
                    else:
                        ai_reply = await asyncio.to_thread(self.generate, user_message, self.username)
                    print(f"[UserBotManager] [Kimi] Generated reply: {ai_reply}")
                except Exception as gen_exc:
                    print(f"[UserBotManager] [Kimi] Failed to generate reply for {self.user.username}: {gen_exc}")
                    ai_reply = None
                # Store message in DB, replied=False
                from chat.models import UserProfile
                # Check agent_auto_reply
                profile = await sync_to_async(UserProfile.objects.get)(user=self.user)
                auto_reply = profile.agent_auto_reply
                user_approved_reply = False
                score = None
                reply_message = None
                if auto_reply:
                    user_approved_reply = True
                    score = 100
                    reply_message = ai_reply
                chat_msg = await sync_to_async(ChatMessage.objects.create)(
                    user=self.user,
                    contact=contact,
                    timestamp=datetime.now(),
                    message=user_message,
                    ai_generated_message=ai_reply,
                    user_approved_reply=user_approved_reply,
                    reply_sent=False,
                    platform='Telegram',
                    telegram_chat_id=getattr(event, 'chat_id', None),
                    telegram_message_id=getattr(event, 'id', None),
                    score=score,
                    reply_message=reply_message,
                )
                print(f"[UserBotManager] ChatMessage created in DB for {self.user.username}, id={chat_msg.id}")
                await asyncio.to_thread(classify_new_message, chat_msg.id)
                await asyncio.to_thread(embed_new_message, chat_msg.id)
                # If auto_reply, send immediately and run next pipeline
                if auto_reply:
                    try:
                        if chat_msg.telegram_chat_id and chat_msg.telegram_message_id:
                            print(f"[UserBotManager] [AutoReply] Sending reply to chat_id={chat_msg.telegram_chat_id}, message_id={chat_msg.telegram_message_id} for message {chat_msg.id} by {self.user.username}")
                            await self.client.send_message(
                                entity=chat_msg.telegram_chat_id,
                                message=chat_msg.reply_message,
                                reply_to=chat_msg.telegram_message_id
                            )
                        else:
                            contact = chat_msg.contact
                            peer = contact.telegram_user_id or contact.telegram_username
                            if peer is None:
                                print(f"[UserBotManager] [AutoReply] WARNING: No valid peer for message {chat_msg.id} by {self.user.username}. Marking as sent and skipping.")
                                chat_msg.reply_sent = True
                                await sync_to_async(chat_msg.save)()
                                return
                            print(f"[UserBotManager] [AutoReply] Sending fallback reply to {peer} for message {chat_msg.id} by {self.user.username}")
                            await self.client.send_message(peer, chat_msg.reply_message)
                        chat_msg.reply_sent = True
                        await sync_to_async(chat_msg.save)()
                        print(f"[UserBotManager] [AutoReply] Reply sent and marked for message {chat_msg.id} by {self.user.username}")
                        # Ensure classification and embedding are run before returning
                        await asyncio.to_thread(classify_new_message, chat_msg.id)
                        await asyncio.to_thread(embed_new_message, chat_msg.id)
                        # Reload from DB and check reply_sent before returning
                        from chat.models import ChatMessage as ChatMessageModel
                        latest_msg = await sync_to_async(ChatMessageModel.objects.get)(id=chat_msg.id)
                        if latest_msg.reply_sent:
                            return
                    except Exception as e:
                        print(f"[UserBotManager] [AutoReply] Failed to send reply for message {chat_msg.id} by {self.user.username}: {e}")
                        logging.exception(f"[AutoReply] Failed to send reply for message {chat_msg.id}: {e}")
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
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._start_with_pin_handling())
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self.thread = t

    async def _start_with_pin_handling(self):
        from telethon.errors import SessionPasswordNeededError
        telegram_obj = await sync_to_async(Telegram.objects.get)(user=self.user)
        print(f"[UserBotManager] _start_with_pin_handling for {self.user.username}")
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        self._setup_handlers()
        try:
            await self.client.connect()
            print(f"[UserBotManager] Connected to Telegram for {self.user.username}")
            if not await self.client.is_user_authorized():
                print(f"[UserBotManager] Not authorized, starting authentication for {self.user.username}")
                phone = telegram_obj.telegram_mobile_number
                await self.client.send_code_request(phone)
                print(f"[UserBotManager] Code request sent to {phone}")
                # Set pin_required True and wait for login code from frontend
                telegram_obj.pin_required = True
                await sync_to_async(telegram_obj.save)()
                # Wait for frontend to provide login code (poll DB)
                while telegram_obj.pin_required:
                    print(f"[UserBotManager] Waiting for login code for {self.user.username}...")
                    await asyncio.sleep(2)
                    await sync_to_async(telegram_obj.refresh_from_db)()
                print(f"[UserBotManager] Login code received for {self.user.username}, trying to sign in with code")
                try:
                    # sign_in with code (telegram_obj.telegram_pin_code used for login code)
                    await self.client.sign_in(phone, telegram_obj.telegram_pin_code)
                    telegram_obj.pin_required = False
                    await sync_to_async(telegram_obj.save)()
                    print(f"[UserBotManager] Signed in with login code for {self.user.username}")
                except SessionPasswordNeededError:
                    print(f"[UserBotManager] 2FA PIN required for {self.user.username}, waiting for frontend to provide PIN")
                    telegram_obj.pin_required = True
                    await sync_to_async(telegram_obj.save)()
                    # Wait for frontend to provide 2FA PIN (poll DB)
                    while telegram_obj.pin_required:
                        print(f"[UserBotManager] Waiting for 2FA PIN for {self.user.username}...")
                        await asyncio.sleep(2)
                        await sync_to_async(telegram_obj.refresh_from_db)()
                    print(f"[UserBotManager] 2FA PIN received for {self.user.username}, trying to sign in with PIN")
                    try:
                        await self.client.sign_in(phone, telegram_obj.telegram_pin_code)
                        telegram_obj.pin_required = False
                        await sync_to_async(telegram_obj.save)()
                        print(f"[UserBotManager] Signed in successfully after 2FA PIN for {self.user.username}")
                    except Exception as e:
                        print(f"[UserBotManager] 2FA PIN incorrect after waiting for {self.user.username}: {e}")
                        telegram_obj.pin_required = True
                        await sync_to_async(telegram_obj.save)()
                        return
                except Exception as e:
                    print(f"[UserBotManager] Exception during sign_in for {self.user.username}: {e}")
                    # Do NOT set pin_required for generic errors (e.g., invalid api_id/api_hash)
                    return
            else:
                print(f"[UserBotManager] Already authorized for {self.user.username}")
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
                # Print count of messages needing user approval (not yet approved and not yet sent)
                pending_approval = await sync_to_async(lambda: list(ChatMessage.objects.select_related('contact').filter(user=self.user, user_approved_reply=False, reply_sent=False, platform='Telegram')))()
                pending_approval_count = len(pending_approval)
                print(f"[UserBotManager] Pending messages needing approval for {self.user.username}: {pending_approval_count}")

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
                        # Feedback pipeline (DB only, per message)
                        asyncio.create_task(asyncio.to_thread(classify_new_message, msg.id))
                        asyncio.create_task(asyncio.to_thread(embed_new_message, msg.id))
                    except Exception as e:
                        print(f"[UserBotManager] Failed to send reply for message {msg.id} by {self.user.username}: {e}")
                        logging.exception(f"Failed to send reply for message {msg.id}: {e}")
                await asyncio.sleep(2)  # Polling interval
            print(f"[UserBotManager] Exiting _background_reply_sender for {self.user.username}")
            await client_task

    def stop(self):
        print(f"[UserBotManager] Stopping userbot for {self.user.username}")
        if self.running:
            self.running = False
            if hasattr(self, 'loop') and self.loop and self.client:
                def _disconnect():
                    coro_or_future = self.client.disconnect()
                    if asyncio.iscoroutine(coro_or_future):
                        asyncio.create_task(coro_or_future)
                    else:
                        # It's a Future, so just add a done callback or ignore
                        pass
                self.loop.call_soon_threadsafe(_disconnect)
            print(f"[UserBotManager] Userbot stopped for {self.user.username}")
