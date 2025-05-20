import asyncio
import logging
import os
import random
import re
import sys
import time
from typing import Optional, Tuple, Dict, List, Union
import aiohttp

import yt_dlp
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
        self.invidious_instances = [
            "https://yewtu.be",
            "https://inv.riverside.rocks",
            "https://invidious.snopyta.org",
            "https://invidious.privacydev.net"
        ]

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.request_delay:
            await asyncio.sleep(self.request_delay - elapsed)
        self.last_request = time.time()
        self.request_delay = random.uniform(1.5, 2.5)

    def _get_ydl_opts(self, audio_only: bool = True) -> Dict:
        """Get options for yt-dlp based on download type."""
        return {
            'format': 'bestaudio/best' if audio_only else 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            'quiet': True,
            'no_warnings': True,
            'geo_bypass': True,
            'force_ipv4': True,
            'socket_timeout': 30,
            'retries': 3,
            'user_agent': random.choice(self.user_agents),
            'referer': 'https://www.youtube.com/',
            'noplaylist': True,
            'logger': logger,
            'extract_flat': False,
        }

    async def _get_from_invidious(self, query: str) -> Optional[Dict]:
        """Fallback to Invidious API if YouTube blocks the request."""
        for base in self.invidious_instances:
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"{base}/api/v1/search?q={query}"
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            results = await resp.json()
                            if results and isinstance(results, list):
                                video = next((v for v in results if v['type'] == 'video'), None)
                                if video:
                                    return {
                                        'id': video['videoId'],
                                        'title': video['title'],
                                        'duration': video.get('lengthSeconds', 0),
                                        'thumbnail': next(
                                            (t['url'] for t in video.get('videoThumbnails', []) 
                                             if t.get('quality') == 'medium'),
                                            video.get('videoThumbnails', [{}])[0].get('url', '')
                                        ),
                                        'url': f"{self.base_url}{video['videoId']}"
                                    }
            except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, IndexError) as e:
                logger.warning(f"Invidious fallback failed on {base}: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error with Invidious {base}: {str(e)}", exc_info=True)
        return None

    async def url(self, message: Message) -> Optional[str]:
        """Extract YouTube URL from message or replied message."""
        try:
            for msg in [message, getattr(message, "reply_to_message", None)]:
                if not msg:
                    continue
                
                # Get all entities and text
                entities = (getattr(msg, "entities", []) or []) + (getattr(msg, "caption_entities", []) or [])
                text = getattr(msg, "text", "") or getattr(msg, "caption", "")
                
                if not text or not entities:
                    continue
                
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
            logger.error(f"URL extraction failed: {str(e)}", exc_info=True)
            return None

    async def details(self, query: str) -> Tuple[Optional[Dict], str]:
        """Get video details from YouTube."""
        try:
            await self._rate_limit()
            url_match = self.url_regex.match(query)
            video_id = url_match.group(5) if url_match else None
            
            if video_id:
                query = f"{self.base_url}{video_id}"
            elif not query.startswith('ytsearch:'):
                query = f"ytsearch:{query}"

            ydl_opts = self._get_ydl_opts()
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.to_thread(ydl.extract_info, query, download=False)
            except yt_dlp.utils.ExtractorError as e:
                if "Sign in to confirm you're not a bot" in str(e):
                    logger.warning("Captcha block, trying Invidious fallback...")
                    fallback = await self._get_from_invidious(query.replace("ytsearch:", ""))
                    if fallback:
                        return fallback, ""
                    return None, "Blocked by YouTube and fallback failed"
                logger.error(f"Extractor error: {str(e)}")
                return None, f"Extraction failed: {str(e)}"
            except Exception as e:
                logger.error(f"Error getting video details: {str(e)}", exc_info=True)
                return None, f"Error: {str(e)}"

            if not info:
                return None, "No results found."

            if 'entries' in info:
                if isinstance(info['entries'], list) and info['entries']:
                    info = info['entries'][0]
                else:
                    return None, "No video found in search results."

            if not info.get('id'):
                return None, "No video ID found."

            video_id = info['id']
            return {
                'id': video_id,
                'title': info.get('title', 'Unknown Title'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                'url': f"{self.base_url}{video_id}"
            }, ""
        except Exception as e:
            logger.error(f"Failed to get video details: {str(e)}", exc_info=True)
            return None, f"Failed to process query: {str(e)}"

    async def exists(self, query: str) -> bool:
        """Check if a video exists."""
        try:
            details, _ = await self.details(query)
            return details is not None
        except Exception as e:
            logger.error(f"Exists check failed: {str(e)}", exc_info=True)
            return False

    async def video(self, video_id: str) -> Tuple[Optional[str], str]:
        """Get direct video stream URL."""
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
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Download error: {str(e)}")
            return None, f"Download failed: {str(e)}"
        except Exception as e:
            logger.error(f"Stream URL error: {str(e)}", exc_info=True)
            return None, f"Error getting stream URL: {str(e)}"

    async def download(self, video_id: str, audio_only: bool = True) -> Tuple[Optional[str], str]:
        """Download video or audio from YouTube."""
        try:
            await self._rate_limit()
            ydl_opts = self._get_ydl_opts(audio_only)
            os.makedirs('downloads', exist_ok=True)
            
            ydl_opts['outtmpl'] = os.path.join('downloads', '%(id)s.%(ext)s')
            
            if audio_only:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
                ydl_opts['format'] = 'bestaudio/best'

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(
                    ydl.extract_info,
                    f"{self.base_url}{video_id}",
                    download=True
                )
                
                path = ydl.prepare_filename(info)
                if audio_only and not path.endswith('.mp3'):
                    new_path = os.path.splitext(path)[0] + '.mp3'
                    if os.path.exists(path):
                        os.rename(path, new_path)
                    path = new_path
                
                return path, ""
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Download error: {str(e)}")
            return None, f"Download failed: {str(e)}"
        except Exception as e:
            logger.error(f"Download error: {str(e)}", exc_info=True)
            return None, f"Error during download: {str(e)}"
