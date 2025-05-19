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

# Configure logging to show all errors in terminal
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
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
        ]

    async def _rate_limit(self):
        """Enforce rate limiting between requests"""
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.request_delay:
            wait_time = self.request_delay - elapsed
            await asyncio.sleep(wait_time)
        self.last_request = time.time()
        self.request_delay = random.uniform(1.5, 2.5)

    def _get_ydl_opts(self, audio_only=True):
        """Get yt-dlp options with anti-detection measures"""
        return {
            'format': 'bestaudio/best' if audio_only else 'best[height<=720]',
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': False,
            'geo_bypass': True,
            'extract_flat': True,
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
            'sleep_interval': random.randint(1, 3),
            'max_sleep_interval': 8,
            'noplaylist': True,
            'logger': logger
        }

    async def extract_url(self, message: Message) -> Optional[str]:
        """Extract YouTube URL from Pyrogram message"""
        try:
            # Check both message and replied message
            for msg in [message, message.reply_to_message]:
                if not msg:
                    continue
                
                # Check text entities
                if msg.entities:
                    for entity in msg.entities:
                        if entity.type == MessageEntityType.URL:
                            text = msg.text or msg.caption
                            if text:
                                url = text[entity.offset:entity.offset + entity.length]
                                if self.url_regex.match(url):
                                    return url
                
                # Check caption entities
                if msg.caption_entities:
                    for entity in msg.caption_entities:
                        if entity.type == MessageEntityType.TEXT_LINK:
                            url = entity.url
                            if self.url_regex.match(url):
                                return url
            
            return None
        except Exception as e:
            logger.error(f"URL extraction error: {str(e)}", exc_info=True)
            return None

    async def process_query(self, query: str) -> Tuple[Optional[Dict], str]:
        """Process YouTube URL or search query"""
        try:
            await self._rate_limit()
            
            # Check if it's a URL
            url_match = self.url_regex.match(query)
            if url_match:
                video_id = url_match.group(5)
                query = f"{self.base_url}{video_id}"
                
            ydl_opts = self._get_ydl_opts()
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Handle search queries
                if not url_match and not query.startswith('ytsearch:'):
                    query = f"ytsearch:{query}"
                
                info = await asyncio.to_thread(
                    ydl.extract_info,
                    query,
                    download=False
                )
                
                if not info:
                    raise ValueError("Empty response from YouTube")
                
                # Handle search results
                if 'entries' in info:
                    if not info['entries']:
                        raise ValueError("No search results found")
                    info = info['entries'][0]
                
                return {
                    'id': info['id'],
                    'title': info.get('title', 'Unknown Title'),
                    'duration': info.get('duration', 0),
                    'thumbnail': f"https://i.ytimg.com/vi/{info['id']}/hqdefault.jpg",
                    'url': f"{self.base_url}{info['id']}"
                }, ""
                
        except yt_dlp.DownloadError as e:
            logger.error(f"YT-DLP Error: {str(e)}")
            if "Sign in to confirm" in str(e):
                return None, "YouTube temporary block. Please try again later."
            return None, "YouTube processing error"
        except Exception as e:
            logger.error(f"Processing error: {str(e)}", exc_info=True)
            return None, "Failed to process request"

    async def get_stream_url(self, video_id: str) -> Tuple[Optional[str], str]:
        """Get direct streaming URL"""
        try:
            await self._rate_limit()
            ydl_opts = self._get_ydl_opts()
            
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

    async def download(self, video_id: str) -> Tuple[Optional[str], str]:
        """Download audio file"""
        try:
            await self._rate_limit()
            ydl_opts = self._get_ydl_opts()
            ydl_opts['outtmpl'] = 'downloads/%(id)s.%(ext)s'
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
                if not path.endswith('.mp3'):
                    new_path = os.path.splitext(path)[0] + '.mp3'
                    os.rename(path, new_path)
                    path = new_path
                
                return path, ""
        except Exception as e:
            logger.error(f"Download error: {str(e)}", exc_info=True)
            return None, "Download failed"
