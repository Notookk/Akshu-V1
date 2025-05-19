import asyncio
import logging
import os
import random
import re
import time
from typing import Optional, Tuple, Union, Dict

import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch

logger = logging.getLogger(__name__)

class YouTubeAPI:
    def __init__(self):
        self.base_url = "https://www.youtube.com/watch?v="
        self.search_url = "ytsearch:"
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.last_request = 0
        self.request_delay = random.uniform(1.5, 3.0)
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
        ]

    async def _rate_limit(self):
        """Enforce rate limiting with random delays"""
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.request_delay:
            await asyncio.sleep(self.request_delay - elapsed)
        self.last_request = time.time()
        self.request_delay = random.uniform(1.5, 3.0)

    def _get_ydl_options(self, audio_only=True):
        """Get yt-dlp options with anti-detection measures"""
        return {
            'format': 'bestaudio/best' if audio_only else 'best[height<=720]',
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'geo_bypass': True,
            'force_ipv4': True,
            'socket_timeout': 30,
            'retries': 3,
            'extractor_args': {
                'youtube': {
                    'skip': ['dash', 'hls'],
                    'player_client': ['android', 'web']
                }
            },
            'user_agent': random.choice(self.user_agents),
            'referer': 'https://www.youtube.com/',
            'throttled_rate': '1M',
            'sleep_interval': random.randint(1, 3)
        }

    async def url(self, message: Message) -> Optional[str]:
        """
        Extract YouTube URL from a Pyrogram message
        Supports both text URLs and TEXT_LINK entities
        """
        try:
            # Check the main message
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        if text:
                            url = text[entity.offset:entity.offset + entity.length]
                            if re.search(self.regex, url):
                                return url

            # Check caption entities
            if message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        if re.search(self.regex, entity.url):
                            return entity.url

            # Check replied message if exists
            if message.reply_to_message:
                return await self.url(message.reply_to_message)

            return None
        except Exception as e:
            logger.error(f"URL extraction failed: {str(e)}")
            return None

    async def process_query(self, query: str) -> Tuple[Optional[Dict], bool]:
        """
        Process a YouTube query or URL
        Returns (video_info, is_search)
        """
        try:
            # Check if it's already a URL
            if re.search(self.regex, query):
                info = await self._safe_extract(query)
                return info, False
            
            # Try as search query
            info = await self._safe_extract(query, is_search=True)
            if 'entries' in info and info['entries']:
                return info['entries'][0], True
            
            raise ValueError("No results found")
            
        except Exception as e:
            logger.error(f"Query processing failed: {str(e)}")
            # Fallback to VideosSearch
            try:
                results = VideosSearch(query, limit=1)
                result = (await results.next())["result"][0]
                return {
                    'id': result['id'],
                    'title': result['title'],
                    'duration': sum(x * int(t) for x, t in zip([60, 1], reversed(result['duration'].split(':')))),
                    'thumbnail': result['thumbnails'][0]['url'].split('?')[0],
                    'url': f"{self.base_url}{result['id']}"
                }, True
            except Exception as fallback_error:
                logger.error(f"Fallback also failed: {str(fallback_error)}")
                return None, False

    async def _safe_extract(self, query: str, is_search: bool = False):
        """Safely extract video info with retry logic"""
        for attempt in range(3):
            try:
                await self._rate_limit()
                ydl_opts = self._get_ydl_options()
                
                if is_search and not query.startswith(self.search_url):
                    query = f"{self.search_url}{query}"
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.to_thread(
                        ydl.extract_info,
                        query,
                        download=False
                    )
                    if not info:
                        raise ValueError("Empty response from YouTube")
                    return info
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == 2:
                    raise
                await asyncio.sleep(1 + attempt)  # Progressive backoff

    async def get_download_url(self, video_id: str, audio_only=True) -> Optional[str]:
        """Get direct download URL for a video"""
        try:
            await self._rate_limit()
            ydl_opts = self._get_ydl_options(audio_only)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(
                    ydl.extract_info,
                    f"{self.base_url}{video_id}",
                    download=False
                )
                return info.get('url')
        except Exception as e:
            logger.error(f"Failed to get download URL: {str(e)}")
            return None

    async def download_media(self, query: str, audio_only=True) -> Optional[str]:
        """Download media file with proper error handling"""
        try:
            video_info, _ = await self.process_query(query)
            if not video_info:
                return None
                
            await self._rate_limit()
            ydl_opts = self._get_ydl_options(audio_only)
            ydl_opts['outtmpl'] = f"downloads/%(id)s.%(ext)s"
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(
                    ydl.extract_info,
                    f"{self.base_url}{video_info['id']}",
                    download=True
                )
                path = ydl.prepare_filename(info)
                
                if audio_only and not path.endswith('.mp3'):
                    new_path = os.path.splitext(path)[0] + '.mp3'
                    os.rename(path, new_path)
                    return new_path
                return path
        except Exception as e:
            logger.error(f"Download failed: {str(e)}")
            return None
