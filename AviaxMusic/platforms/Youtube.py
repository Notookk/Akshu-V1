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

# Configure logging to show errors in terminal
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

class YouTube:
    def __init__(self):
        self.base_url = "https://www.youtube.com/watch?v="
        self.url_pattern = re.compile(
            r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+'
        )
        self.last_request = 0
        self.request_delay = 2.0  # Start with 2 second delay

    def _get_ydl_opts(self, audio_only=True):
        """Get yt-dlp options that actually work"""
        return {
            'format': 'bestaudio/best' if audio_only else 'best[height<=720]',
            'quiet': False,  # Show logs
            'no_warnings': False,
            'ignoreerrors': False,
            'geo_bypass': True,
            'extract_flat': True,
            'force_ipv4': True,
            'socket_timeout': 15,
            'retries': 3,
            'extractor_args': {
                'youtube': {
                    'skip': ['dash', 'hls'],
                    'player_client': ['android']
                }
            },
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'throttled_rate': '1M',
            'noplaylist': True,
            'logger': logger  # Pass our logger to yt-dlp
        }

    async def _rate_limit(self):
        """Simple rate limiting"""
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.request_delay:
            wait_time = self.request_delay - elapsed
            await asyncio.sleep(wait_time)
        self.last_request = time.time()
        # Randomize next delay slightly
        self.request_delay = random.uniform(1.5, 2.5)

    async def extract_url(self, message: Message) -> Optional[str]:
        """Extract URL from message with DEBUG logging"""
        try:
            logger.debug(f"Extracting URL from message: {message}")
            
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
                                if self.url_pattern.match(url):
                                    logger.debug(f"Found URL in text: {url}")
                                    return url
                
                # Check caption entities
                if msg.caption_entities:
                    for entity in msg.caption_entities:
                        if entity.type == MessageEntityType.TEXT_LINK:
                            url = entity.url
                            if self.url_pattern.match(url):
                                logger.debug(f"Found URL in caption: {url}")
                                return url
            
            logger.debug("No valid YouTube URL found in message")
            return None
            
        except Exception as e:
            logger.error(f"Error in extract_url: {str(e)}", exc_info=True)
            return None

    async def process_query(self, query: str) -> Tuple[Optional[Dict], str]:
        """Process query with detailed error handling and logging"""
        try:
            logger.debug(f"Processing query: {query}")
            await self._rate_limit()
            
            # Check if it's a URL
            if self.url_pattern.match(query):
                logger.debug("Processing as URL")
                ydl_opts = self._get_ydl_opts()
                
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = await asyncio.to_thread(
                            ydl.extract_info,
                            query,
                            download=False
                        )
                        
                        if not info:
                            logger.error("Empty response from YouTube")
                            return None, "YouTube returned empty response"
                        
                        logger.debug(f"URL info: {info}")
                        return {
                            'id': info['id'],
                            'title': info.get('title', 'Unknown Title'),
                            'duration': info.get('duration', 0),
                            'thumbnail': f"https://i.ytimg.com/vi/{info['id']}/hqdefault.jpg",
                            'url': query
                        }, ""
                except yt_dlp.DownloadError as e:
                    logger.error(f"YT-DLP Error: {str(e)}")
                    if "Sign in to confirm" in str(e):
                        return None, "YouTube temporary block. Please try again later."
                    return None, "YouTube processing error"
                except Exception as e:
                    logger.error(f"Unexpected error: {str(e)}", exc_info=True)
                    return None, "Failed to process YouTube URL"
            
            # Process as search query
            logger.debug("Processing as search query")
            search_query = f"ytsearch:{query}"
            ydl_opts = self._get_ydl_opts()
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.to_thread(
                        ydl.extract_info,
                        search_query,
                        download=False
                    )
                    
                    if not info or 'entries' not in info or not info['entries']:
                        logger.error("No search results from yt-dlp")
                        # Fallback to VideosSearch
                        try:
                            results = VideosSearch(query, limit=1)
                            search_result = await results.next()
                            if not search_result or not search_result.get('result'):
                                return None, "No results found for your query"
                            
                            video = search_result['result'][0]
                            duration = sum(
                                int(x) * 60 ** i 
                                for i, x in enumerate(reversed(video['duration'].split(':')))
                            
                            return {
                                'id': video['id'],
                                'title': video['title'],
                                'duration': duration,
                                'thumbnail': video['thumbnails'][0]['url'].split('?')[0],
                                'url': f"{self.base_url}{video['id']}"
                            }, ""
                        except Exception as search_error:
                            logger.error(f"Search fallback failed: {str(search_error)}")
                            return None, "Failed to search YouTube"
                    
                    # Get first result
                    video = info['entries'][0]
                    return {
                        'id': video['id'],
                        'title': video.get('title', 'Unknown Title'),
                        'duration': video.get('duration', 0),
                        'thumbnail': f"https://i.ytimg.com/vi/{video['id']}/hqdefault.jpg",
                        'url': f"{self.base_url}{video['id']}"
                    }, ""
                    
            except yt_dlp.DownloadError as e:
                logger.error(f"YT-DLP Search Error: {str(e)}")
                return None, "Search failed. Please try again."
            except Exception as e:
                logger.error(f"Unexpected search error: {str(e)}", exc_info=True)
                return None, "Failed to process search query"
                
        except Exception as e:
            logger.error(f"Critical error in process_query: {str(e)}", exc_info=True)
            return None, "An unexpected error occurred"

    async def get_stream_url(self, video_id: str) -> Tuple[Optional[str], str]:
        """Get direct stream URL with detailed logging"""
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
                    logger.error("No stream URL in response")
                    return None, "Stream URL not available"
                
                logger.debug(f"Got stream URL: {info['url']}")
                return info['url'], ""
                
        except Exception as e:
            logger.error(f"Error getting stream URL: {str(e)}", exc_info=True)
            return None, "Failed to get stream URL"

    async def download(self, video_id: str) -> Tuple[Optional[str], str]:
        """Download audio with detailed logging"""
        try:
            await self._rate_limit()
            ydl_opts = self._get_ydl_opts()
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['outtmpl'] = f'downloads/%(id)s.%(ext)s'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.debug(f"Starting download for {video_id}")
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
                
                logger.debug(f"Download completed: {path}")
                return path, ""
                
        except Exception as e:
            logger.error(f"Download failed: {str(e)}", exc_info=True)
            return None, "Download failed"
