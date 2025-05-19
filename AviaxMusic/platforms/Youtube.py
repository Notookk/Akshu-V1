import asyncio
import logging
import os
import random
import re
import sys
import time
from typing import Optional, Tuple, Dict

import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

class YouTubeAPI:
    def __init__(self):
        self.base_url = "https://www.youtube.com/watch?v="
        self.url_regex = re.compile(
            r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
        )
        self.last_request = 0
        self.request_delay = 2.0
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6...)"
        ]

    async def _rate_limit(self):
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.request_delay:
            await asyncio.sleep(self.request_delay - elapsed)
        self.last_request = time.time()
        self.request_delay = random.uniform(1.5, 2.5)

    def _get_ydl_opts(self, audio_only=True):
        return {
            'format': 'bestaudio/best' if audio_only else 'best[height<=720]',
            'quiet': True,
            'no_warnings': True,
            'geo_bypass': True,
            'extract_flat': True,
            'force_ipv4': True,
            'socket_timeout': 30,
            'retries': 3,
            'user_agent': random.choice(self.user_agents),
            'referer': 'https://www.youtube.com/',
            'noplaylist': True,
            'logger': logger,
        }

    async def url(self, message: Message) -> Optional[str]:
        try:
            for msg in [message, message.reply_to_message]:
                if not msg:
                    continue
                entities = (msg.entities or []) + (msg.caption_entities or [])
                text = msg.text or msg.caption
                if text and entities:
                    for entity in entities:
                        if entity.type == MessageEntityType.URL:
                            url = text[entity.offset:entity.offset + entity.length]
                            if self.url_regex.match(url):
                                return url
                        elif entity.type == MessageEntityType.TEXT_LINK:
                            if self.url_regex.match(entity.url):
                                return entity.url
            return None
        except Exception as e:
            logger.error(f"URL extraction failed: {e}", exc_info=True)
            return None

    async def details(self, query: str) -> Tuple[Optional[Dict], str]:
        try:
            await self._rate_limit()
            url_match = self.url_regex.match(query)
            if url_match:
                video_id = url_match.group(5)
                query = f"{self.base_url}{video_id}"

            ydl_opts = self._get_ydl_opts()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if not url_match and not query.startswith('ytsearch:'):
                    query = f"ytsearch:{query}"

                info = await asyncio.to_thread(ydl.extract_info, query, download=False)

                if not info:
                    return None, "No results"

                if 'entries' in info:
                    info = info['entries'][0]
                    if not info:
                        return None, "No results"

                return {
                    'id': info['id'],
                    'title': info.get('title', 'Unknown Title'),
                    'duration': info.get('duration', 0),
                    'thumbnail': f"https://i.ytimg.com/vi/{info['id']}/hqdefault.jpg",
                    'url': f"{self.base_url}{info['id']}"
                }, ""
        except Exception as e:
            logger.error(f"Failed to get video details: {e}", exc_info=True)
            return None, "Failed to process query"

    async def exists(self, query: str) -> bool:
        """Check if a YouTube video exists or is valid."""
        try:
            details, err = await self.details(query)
            return details is not None
        except Exception as e:
            logger.error(f"Exists check failed: {e}", exc_info=True)
            return False

    async def video(self, video_id: str) -> Tuple[Optional[str], str]:
        try:
            await self._rate_limit()
            ydl_opts = self._get_ydl_opts(audio_only=False)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(
                    ydl.extract_info,
                    f"{self.base_url}{video_id}",
                    download=False
                )
                if not info or not info.get('url'):
                    return None, "No stream URL available"
                return info['url'], ""
        except Exception as e:
            logger.error(f"Stream URL error: {str(e)}", exc_info=True)
            return None, "Failed to get stream URL"

    async def download(self, video_id: str, audio_only=True) -> Tuple[Optional[str], str]:
        try:
            await self._rate_limit()
            ydl_opts = self._get_ydl_opts(audio_only)
            ydl_opts['outtmpl'] = 'downloads/%(id)s.%(ext)s'
            if audio_only:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(
                    ydl.extract_info,
                    f"{self.base_url}{video_id}",
                    download=True
                )
                path = ydl.prepare_filename(info)
                if audio_only and not path.endswith('.mp3'):
                    new_path = os.path.splitext(path)[0] + '.mp3'
                    os.rename(path, new_path)
                    path = new_path
                return path, ""
        except Exception as e:
            logger.error(f"Download error: {str(e)}", exc_info=True)
            return None, "Download failed"
