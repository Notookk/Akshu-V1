import asyncio
import logging
import os
import random
import re
import sys
import time
from typing import Optional, Dict, Tuple, List
import aiohttp
from urllib.parse import quote

from pyrogram.enums import MessageEntityType
from pyrogram.types import Message

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


class YouTubeAPI:
    def __init__(self):
        self.url_regex = re.compile(
            r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
        )
        self.invidious_instances = [
            "https://yewtu.be",
            "https://inv.odyssey346.dev",
            "https://invidious.flokinet.to",
            "https://vid.puffyan.us",
            "https://inv.tux.pizza"
        ]
        self.current_instance_index = 0
        self.last_request = 0
        self.request_delay = 2.0
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    async def _rate_limit(self) -> None:
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.request_delay:
            delay = self.request_delay - elapsed + random.uniform(0, 0.5)
            await asyncio.sleep(delay)
        self.last_request = time.time()
        self.request_delay = random.uniform(1.5, 3.0)

    def _get_next_instance(self) -> str:
        instance = self.invidious_instances[self.current_instance_index]
        self.current_instance_index = (self.current_instance_index + 1) % len(self.invidious_instances)
        return instance

    async def _get_from_invidious(self, query: str) -> Optional[Dict]:
        for _ in range(len(self.invidious_instances)):
            base = self._get_next_instance()
            try:
                async with aiohttp.ClientSession(headers=self.headers) as session:
                    url = f"{base}/api/v1/search?q={quote(query)}"
                    async with session.get(url, timeout=15) as resp:
                        if resp.status == 200:
                            results = await resp.json()
                            if results and isinstance(results, list):
                                video = next((v for v in results if v.get('type') == 'video'), None)
                                if video:
                                    return {
                                        'id': video.get('videoId'),
                                        'title': video.get('title', 'Unknown Title'),
                                        'duration': video.get('lengthSeconds', 0),
                                        'thumbnail': f"{base}/vi/{video.get('videoId')}/hqdefault.jpg",
                                        'url': f"{base}/watch?v={video.get('videoId')}"
                                    }
                        elif resp.status == 429:
                            await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Invidious request failed on {base}: {str(e)}")
        return None

    async def url(self, message: Message) -> Optional[str]:
        try:
            messages_to_check = [message]
            if message.reply_to_message:
                messages_to_check.append(message.reply_to_message)

            for msg in messages_to_check:
                if not msg:
                    continue

                text = msg.text or msg.caption or ""
                entities = (msg.entities or []) + (msg.caption_entities or [])

                for entity in entities:
                    try:
                        if entity.type == MessageEntityType.URL:
                            url = text[entity.offset:entity.offset + entity.length]
                            if match := self.url_regex.fullmatch(url):
                                return f"{self._get_next_instance()}/watch?v={match.group(5)}"
                        elif entity.type == MessageEntityType.TEXT_LINK:
                            if match := self.url_regex.fullmatch(entity.url):
                                return f"{self._get_next_instance()}/watch?v={match.group(5)}"
                    except Exception:
                        continue
            return None
        except Exception as e:
            logger.error(f"URL extraction failed: {str(e)}", exc_info=True)
            return None

    async def details(self, query: str) -> Tuple[Optional[Dict], str]:
        try:
            await self._rate_limit()

            if query.startswith("http") and (match := self.url_regex.match(query)):
                query = match.group(5)

            video = await self._get_from_invidious(query)
            return (video, "") if video else (None, "No video found")

        except Exception as e:
            logger.error(f"Failed to process query: {str(e)}", exc_info=True)
            return None, f"Failed to process query: {str(e)}"

    async def exists(self, query: str) -> bool:
        try:
            details, _ = await self.details(query)
            return details is not None
        except Exception as e:
            logger.error(f"Exists check failed: {str(e)}", exc_info=True)
            return False

    async def video(self, video_id: str) -> Tuple[Optional[str], str]:
        try:
            await self._rate_limit()
            for _ in range(len(self.invidious_instances)):
                base = self._get_next_instance()
                try:
                    async with aiohttp.ClientSession(headers=self.headers) as session:
                        url = f"{base}/api/v1/videos/{video_id}"
                        async with session.get(url, timeout=15) as resp:
                            if resp.status == 200:
                                info = await resp.json()
                                if info.get('formatStreams'):
                                    best = sorted(info['formatStreams'], key=lambda x: x.get('bitrate', 0), reverse=True)[0]
                                    return best.get('url'), ""
                except Exception as e:
                    logger.warning(f"Stream request failed on {base}: {str(e)}")
            return None, "Stream URL not found"
        except Exception as e:
            logger.error(f"Stream error: {str(e)}", exc_info=True)
            return None, f"Stream error: {str(e)}"

    async def download(self, video_id: str, audio_only: bool = True) -> Tuple[Optional[str], str]:
        try:
            await self._rate_limit()
            for _ in range(len(self.invidious_instances)):
                base = self._get_next_instance()
                try:
                    async with aiohttp.ClientSession(headers=self.headers) as session:
                        url = f"{base}/api/v1/videos/{video_id}"
                        async with session.get(url, timeout=15) as resp:
                            if resp.status == 200:
                                info = await resp.json()
                                streams = info.get('adaptiveFormats' if audio_only else 'formatStreams', [])
                                filtered = [s for s in streams if 'url' in s and (s.get('type', '').startswith('audio/') if audio_only else True)]
                                if filtered:
                                    best = sorted(filtered, key=lambda x: x.get('bitrate', 0), reverse=True)[0]
                                    stream_url = best['url']

                                    os.makedirs('downloads', exist_ok=True)
                                    timestamp = int(time.time())
                                    ext = 'mp3' if audio_only else 'mp4'
                                    filename = os.path.join('downloads', f'{video_id}_{timestamp}.{ext}')

                                    async with session.get(stream_url) as r:
                                        with open(filename, 'wb') as f:
                                            while True:
                                                chunk = await r.content.read(1024)
                                                if not chunk:
                                                    break
                                                f.write(chunk)

                                    return filename, ""
                except Exception as e:
                    logger.warning(f"Download failed on {base}: {str(e)}")
            return None, "Failed to download"
        except Exception as e:
            logger.error(f"Download error: {str(e)}", exc_info=True)
            return None, f"Download error: {str(e)}"
