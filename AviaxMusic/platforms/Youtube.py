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
        self.invidious_instances = [
            "https://yewtu.be",
            "https://inv.odyssey346.dev",
            "https://invidious.flokinet.to",
            "https://vid.puffyan.us",
            "https://inv.tux.pizza"
        ]
        self.current_instance_index = 0

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests with jitter."""
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.request_delay:
            delay = self.request_delay - elapsed + random.uniform(0, 0.5)
            await asyncio.sleep(delay)
        self.last_request = time.time()
        self.request_delay = random.uniform(1.5, 3.0)

    def _get_ydl_opts(self, audio_only: bool = True) -> Dict:
        """Get optimized options for yt-dlp."""
        return {
            'format': 'bestaudio/best' if audio_only else 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_ipv4': True,
            'socket_timeout': 30,
            'retries': 3,
            'user_agent': random.choice(self.user_agents),
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'ratelimit': 1048576,
            'extractor_args': {
                'youtube': {
                    'skip': ['dash', 'hls']
                }
            }
        }

    def _get_next_instance(self) -> str:
        """Get next Invidious instance in rotation."""
        instance = self.invidious_instances[self.current_instance_index]
        self.current_instance_index = (self.current_instance_index + 1) % len(self.invidious_instances)
        return instance

    async def _get_from_invidious(self, query: str) -> Optional[Dict]:
        """Fallback to Invidious API with rotation."""
        for _ in range(min(3, len(self.invidious_instances))):
            base = self._get_next_instance()
            try:
                async with aiohttp.ClientSession() as session:
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
                                        'thumbnail': f"https://i.ytimg.com/vi/{video.get('videoId')}/hqdefault.jpg",
                                        'url': f"{self.base_url}{video.get('videoId')}"
                                    }
                        elif resp.status == 429:
                            await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Invidious request failed on {base}: {str(e)}")
        return None

    async def _extract_info_with_retry(self, ydl, query: str, max_retries: int = 2) -> Optional[Dict]:
        """Try to extract info with retries."""
        for attempt in range(max_retries):
            try:
                return await asyncio.to_thread(ydl.extract_info, query, download=False)
            except yt_dlp.utils.DownloadError as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(1)
            except Exception as e:
                raise
        return None

    async def url(self, message: Message) -> Optional[str]:
        """Extract YouTube URL from message."""
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
                    except Exception:
                        continue
            return None
        except Exception as e:
            logger.error(f"URL extraction failed: {str(e)}", exc_info=True)
            return None

    async def details(self, query: str) -> Tuple[Optional[Dict], str]:
        """Get video details with robust error handling."""
        try:
            await self._rate_limit()
            
            url_match = self.url_regex.match(query)
            if url_match:
                video_id = url_match.group(5)
                query = f"{self.base_url}{video_id}"
            elif not query.startswith(('ytsearch:', 'http')):
                query = f"ytsearch:{query}"

            ydl_opts = self._get_ydl_opts()
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await self._extract_info_with_retry(ydl, query)
                    
                    if not info:
                        fallback = await self._get_from_invidious(query.replace("ytsearch:", ""))
                        return (fallback, "") if fallback else (None, "No results found")
                    
                    if 'entries' in info:
                        if isinstance(info['entries'], list) and info['entries']:
                            info = info['entries'][0]
                        else:
                            fallback = await self._get_from_invidious(query.replace("ytsearch:", ""))
                            return (fallback, "") if fallback else (None, "No videos found")

                    if not info.get('id'):
                        return None, "No video ID found"

                    video_id = info['id']
                    return {
                        'id': video_id,
                        'title': info.get('title', 'Unknown Title'),
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                        'url': f"{self.base_url}{video_id}"
                    }, ""
                    
            except yt_dlp.utils.ExtractorError as e:
                if "Sign in" in str(e):
                    fallback = await self._get_from_invidious(query.replace("ytsearch:", ""))
                    return (fallback, "") if fallback else (None, "Blocked by YouTube")
                return None, f"YouTube error: {str(e)}"
                
            except Exception as e:
                logger.error(f"Processing error: {str(e)}", exc_info=True)
                return None, f"Processing error: {str(e)}"

        except Exception as e:
            logger.error(f"Failed to process query: {str(e)}", exc_info=True)
            return None, f"Failed to process query: {str(e)}"

    async def exists(self, query: str) -> bool:
        """Check if video exists."""
        try:
            details, _ = await self.details(query)
            return details is not None
        except Exception as e:
            logger.error(f"Exists check failed: {str(e)}", exc_info=True)
            return False

    async def video(self, video_id: str) -> Tuple[Optional[str], str]:
        """Get video stream URL."""
        try:
            await self._rate_limit()
            ydl_opts = self._get_ydl_opts(audio_only=False)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await self._extract_info_with_retry(ydl, f"{self.base_url}{video_id}")
                
                if not info or not info.get('url'):
                    return None, "No stream URL available"
                
                return info['url'], ""
                
        except yt_dlp.utils.DownloadError as e:
            return None, f"Download failed: {str(e)}"
        except Exception as e:
            logger.error(f"Stream error: {str(e)}", exc_info=True)
            return None, f"Stream error: {str(e)}"

    async def download(self, video_id: str, audio_only: bool = True) -> Tuple[Optional[str], str]:
        """Download video/audio with unique filenames."""
        try:
            await self._rate_limit()
            ydl_opts = self._get_ydl_opts(audio_only)
            os.makedirs('downloads', exist_ok=True)
            
            timestamp = int(time.time())
            ext = 'mp3' if audio_only else 'mp4'
            ydl_opts['outtmpl'] = os.path.join('downloads', f'{video_id}_{timestamp}.%(ext)s')
            
            if audio_only:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await self._extract_info_with_retry(ydl, f"{self.base_url}{video_id}", download=True)
                
                path = ydl.prepare_filename(info)
                if audio_only and not path.endswith('.mp3'):
                    new_path = os.path.splitext(path)[0] + '.mp3'
                    try:
                        if os.path.exists(path):
                            os.rename(path, new_path)
                        path = new_path
                    except OSError:
                        pass
                
                return path, ""
                
        except yt_dlp.utils.DownloadError as e:
            return None, f"Download failed: {str(e)}"
        except Exception as e:
            logger.error(f"Download error: {str(e)}", exc_info=True)
            return None, f"Download error: {str(e)}"
