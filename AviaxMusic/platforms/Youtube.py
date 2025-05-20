import asyncio
import logging
import os
import random
import re
import sys
import time
from typing import Optional, Tuple, Dict, List
import aiohttp
from urllib.parse import quote

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
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.3 Safari/605.1.15",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.3 Mobile/15E148 Safari/604.1"
        ]
        # Updated and verified Invidious instances
        self.invidious_instances = [
            "https://yewtu.be",  # Reliable European instance
            "https://inv.odyssey346.dev",  # Newer alternative
            "https://invidious.flokinet.to",  # Well-maintained instance
            "https://vid.puffyan.us",  # Popular US-based instance
            "https://inv.tux.pizza"  # Backup instance
        ]
        self.current_instance_index = 0

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests with jitter."""
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.request_delay:
            delay = self.request_delay - elapsed + random.uniform(0, 0.5)  # Add jitter
            await asyncio.sleep(delay)
        self.last_request = time.time()
        # Dynamic delay adjustment
        self.request_delay = random.uniform(1.5, 3.0)

    def _get_ydl_opts(self, audio_only: bool = True) -> Dict:
        """Get optimized options for yt-dlp based on download type."""
        opts = {
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
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'ratelimit': 1048576,  # 1MB/s limit to avoid being blocked
        }
        if audio_only:
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        return opts

    def _get_next_instance(self) -> str:
        """Get the next Invidious instance in round-robin fashion."""
        instance = self.invidious_instances[self.current_instance_index]
        self.current_instance_index = (self.current_instance_index + 1) % len(self.invidious_instances)
        return instance

    async def _get_from_invidious(self, query: str) -> Optional[Dict]:
        """Improved Invidious fallback with better error handling and instance rotation."""
        max_attempts = min(3, len(self.invidious_instances))
        
        for attempt in range(max_attempts):
            base = self._get_next_instance()
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"{base}/api/v1/search?q={quote(query)}&type=video"
                    headers = {
                        'User-Agent': random.choice(self.user_agents),
                        'Accept': 'application/json'
                    }
                    
                    async with session.get(url, headers=headers, timeout=10) as resp:
                        if resp.status == 200:
                            results = await resp.json()
                            if results and isinstance(results, list):
                                for video in results:
                                    if video.get('type') == 'video':
                                        thumbnails = video.get('videoThumbnails', [])
                                        return {
                                            'id': video.get('videoId'),
                                            'title': video.get('title', 'Unknown Title'),
                                            'duration': video.get('lengthSeconds', 0),
                                            'thumbnail': self._select_best_thumbnail(thumbnails),
                                            'url': f"{self.base_url}{video.get('videoId')}"
                                        }
                        elif resp.status == 429:
                            logger.warning(f"Rate limited on {base}, trying next instance")
                            await asyncio.sleep(1)  # Brief cooldown
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"Invidious request failed on {base}: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error with Invidious {base}: {str(e)}", exc_info=True)
            
            if attempt < max_attempts - 1:
                await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
        
        return None

    def _select_best_thumbnail(self, thumbnails: List[Dict]) -> str:
        """Select the best available thumbnail with fallbacks."""
        if not thumbnails:
            return ""
        
        # Try to find the best quality available
        for quality in ['high', 'medium', 'default']:
            for thumb in thumbnails:
                if thumb.get('quality') == quality:
                    return thumb.get('url', '')
        
        # Fallback to first available thumbnail
        return thumbnails[0].get('url', '') if thumbnails else ""

    async def url(self, message: Message) -> Optional[str]:
        """More robust URL extraction from messages."""
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
                            if self.url_regex.fullmatch(url):
                                return url
                        elif entity.type == MessageEntityType.TEXT_LINK:
                            if self.url_regex.fullmatch(entity.url):
                                return entity.url
                    except (IndexError, AttributeError):
                        continue
            return None
        except Exception as e:
            logger.error(f"URL extraction failed: {str(e)}", exc_info=True)
            return None

    async def details(self, query: str) -> Tuple[Optional[Dict], str]:
        """Enhanced video details fetching with better fallback handling."""
        try:
            await self._rate_limit()
            
            # Check if it's already a YouTube URL
            url_match = self.url_regex.match(query)
            if url_match:
                video_id = url_match.group(5)
                query = f"{self.base_url}{video_id}"
            elif not query.startswith('ytsearch:'):
                query = f"ytsearch:{query}"

            ydl_opts = self._get_ydl_opts()
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.to_thread(ydl.extract_info, query, download=False)
                    
                    if not info:
                        return None, "No results found."
                    
                    # Handle search results
                    if 'entries' in info:
                        if isinstance(info['entries'], list):
                            if not info['entries']:
                                return None, "No videos found in search results."
                            info = info['entries'][0]
                        else:
                            return None, "Invalid search results format."

                    if not info.get('id'):
                        logger.warning("No video ID found, trying Invidious fallback")
                        fallback = await self._get_from_invidious(query.replace("ytsearch:", ""))
                        if fallback:
                            return fallback, ""
                        return None, "No video ID found and fallback failed"

                    video_id = info['id']
                    return {
                        'id': video_id,
                        'title': info.get('title', 'Unknown Title'),
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                        'url': f"{self.base_url}{video_id}"
                    }, ""
                    
            except yt_dlp.utils.ExtractorError as e:
                if "Sign in to confirm you're not a bot" in str(e):
                    logger.warning("YouTube captcha block detected, using Invidious fallback")
                    fallback = await self._get_from_invidious(query.replace("ytsearch:", ""))
                    if fallback:
                        return fallback, ""
                    return None, "Blocked by YouTube and fallback failed"
                logger.error(f"Extractor error: {str(e)}")
                return None, f"Extraction failed: {str(e)}"
                
            except Exception as e:
                logger.error(f"Error getting video details: {str(e)}", exc_info=True)
                return None, f"Error: {str(e)}"

        except Exception as e:
            logger.error(f"Failed to get video details: {str(e)}", exc_info=True)
            return None, f"Failed to process query: {str(e)}"

    async def exists(self, query: str) -> bool:
        """More efficient existence check."""
        try:
            details, _ = await self.details(query)
            return details is not None
        except Exception as e:
            logger.error(f"Exists check failed: {str(e)}", exc_info=True)
            return False

    async def video(self, video_id: str) -> Tuple[Optional[str], str]:
        """Improved stream URL fetching with better error handling."""
        try:
            await self._rate_limit()
            ydl_opts = self._get_ydl_opts(audio_only=False)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(
                    ydl.extract_info,
                    f"{self.base_url}{video_id}",
                    download=False
                )
                
                if not info:
                    return None, "No video information available"
                
                if not info.get('url'):
                    # Try alternative formats if primary URL not available
                    for fmt in info.get('formats', []):
                        if fmt.get('url'):
                            return fmt['url'], ""
                    return None, "No stream URL available"
                
                return info['url'], ""
                
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Download error: {str(e)}")
            return None, f"Download failed: {str(e)}"
        except Exception as e:
            logger.error(f"Stream URL error: {str(e)}", exc_info=True)
            return None, f"Error getting stream URL: {str(e)}"

    async def download(self, video_id: str, audio_only: bool = True) -> Tuple[Optional[str], str]:
        """More reliable download method with better file handling."""
        try:
            await self._rate_limit()
            ydl_opts = self._get_ydl_opts(audio_only)
            os.makedirs('downloads', exist_ok=True)
            
            # Unique filename to avoid conflicts
            timestamp = int(time.time())
            ext = 'mp3' if audio_only else 'mp4'
            ydl_opts['outtmpl'] = os.path.join('downloads', f'{video_id}_{timestamp}.%(ext)s')
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.to_thread(
                        ydl.extract_info,
                        f"{self.base_url}{video_id}",
                        download=True
                    )
                    
                    path = ydl.prepare_filename(info)
                    if audio_only and not path.endswith('.mp3'):
                        new_path = os.path.splitext(path)[0] + '.mp3'
                        try:
                            if os.path.exists(path):
                                os.rename(path, new_path)
                            path = new_path
                        except OSError as e:
                            logger.warning(f"Failed to rename file: {str(e)}")
                    
                    return path, ""
                    
            except yt_dlp.utils.DownloadError as e:
                logger.error(f"Download error: {str(e)}")
                return None, f"Download failed: {str(e)}"
                
        except Exception as e:
            logger.error(f"Download error: {str(e)}", exc_info=True)
            return None, f"Error during download: {str(e)}"
