import os
import re
import textwrap
import logging

import aiofiles
import aiohttp
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from youtubesearchpython.__future__ import VideosSearch

# Basic logger setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
LOGGER = logging.getLogger(__name__)

def sanitize_filename(filename):
    # Remove or replace any disallowed characters for filenames
    return re.sub(r'[\\/*?:"<>|]', "_", filename)

def file_exists(path):
    if not os.path.isfile(path):
        LOGGER.error(f"Required file does not exist: {path}")
        return False
    return True

FAILED = "AviaxMusic/assets/bot.jpg"  # Make sure this file exists

def changeImageSize(maxWidth, maxHeight, image):
    widthRatio = maxWidth / image.size[0]
    heightRatio = maxHeight / image.size[1]
    newWidth = int(widthRatio * image.size[0])
    newHeight = int(heightRatio * image.size[1])
    newImage = image.resize((newWidth, newHeight))
    return newImage

def add_corners(im):
    bigsize = (im.size[0] * 3, im.size[1] * 3)
    mask = Image.new("L", bigsize, 0)
    ImageDraw.Draw(mask).ellipse((0, 0) + bigsize, fill=255)
    mask = mask.resize(im.size, Image.LANCZOS)
    mask = ImageChops.darker(mask, im.split()[-1])
    im.putalpha(mask)

async def get_user_profile_pic(app, user_id):
    """
    Attempts to download the user's profile photo.
    Returns the path to the downloaded photo, or bot.jpg if unavailable.
    """
    try:
        user = await app.get_users(user_id)
        if hasattr(user, "photo") and hasattr(user.photo, "big_file_id"):
            try:
                photo_path = await app.download_media(
                    user.photo.big_file_id,
                    file_name=f"cache/{sanitize_filename(str(user_id))}_photo.jpg"
                )
                if photo_path and os.path.isfile(photo_path):
                    return photo_path
            except Exception as e:
                LOGGER.error(f"Could not download user photo: {e}")
    except Exception as e:
        LOGGER.error(f"Could not fetch user: {e}")
    return FAILED

async def gen_thumb(videoid, user_id, app):
    try:
        safe_user_id = sanitize_filename(str(user_id))
        safe_videoid = sanitize_filename(str(videoid))
        cached_path = f"cache/{safe_videoid}_{safe_user_id}.png"
        thumb_path = f"cache/thumb{safe_videoid}.png"
        chop_path = f"cache/chop{safe_videoid}.png"
        cropped_path = f"cache/cropped{safe_videoid}.png"
        temp_path = f"cache/temp{safe_videoid}.png"

        if os.path.isfile(cached_path):
            return cached_path

        # Get user profile pic or fallback
        user_image_path = await get_user_profile_pic(app, user_id)
        if not file_exists(user_image_path):
            return None

        url = f"https://www.youtube.com/watch?v={videoid}"
        try:
            results = VideosSearch(url, limit=1)
            data = (await results.next())["result"]
            if not data:
                raise Exception("No video results found.")
            result = data[0]
            title = re.sub("\W+", " ", result.get("title", "Unsupported Title")).title()
            duration = result.get("duration", "Unknown")
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        except Exception as e:
            LOGGER.error(f"Error getting video info: {e}")
            title = "Unsupported Title"
            duration = "Unknown"
            thumbnail = None

        # Download thumbnail
        if thumbnail:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(thumbnail) as resp:
                        if resp.status == 200:
                            async with aiofiles.open(thumb_path, mode="wb") as f:
                                await f.write(await resp.read())
            except Exception as e:
                LOGGER.error(f"Failed to download thumbnail: {e}")

        # Create rounded avatar (user profile or fallback)
        try:
            xy = Image.open(user_image_path)
            a = Image.new("L", [640, 640], 0)
            b = ImageDraw.Draw(a)
            b.pieslice([(0, 0), (640, 640)], 0, 360, fill=255, outline="white")
            if a.size != xy.size:
                a = a.resize(xy.size, Image.LANCZOS)
            c = np.array(xy)
            d = np.array(a)
            e = np.dstack((c, d))
            f = Image.fromarray(e)
            x = f.resize((107, 107))
        except Exception as e:
            LOGGER.error(f"Error creating avatar: {e}")
            return FAILED if file_exists(FAILED) else None

        # Use downloaded YouTube thumbnail or fallback to default
        if not os.path.isfile(thumb_path):
            LOGGER.error(f"Thumbnail image not found: {thumb_path}, using default avatar.")
            return FAILED if file_exists(FAILED) else None

        try:
            youtube = Image.open(thumb_path)
            circle_path = "AviaxMusic/assets/circle.png"
            if not file_exists(circle_path):
                return FAILED if file_exists(FAILED) else None
            bg = Image.open(circle_path)
            image1 = changeImageSize(1280, 720, youtube)
            image2 = image1.convert("RGBA")
            background = image2.filter(filter=ImageFilter.BoxBlur(30))
            enhancer = ImageEnhance.Brightness(background)
            background = enhancer.enhance(0.6)

            image3 = changeImageSize(1280, 720, bg)
            image5 = image3.convert("RGBA")
            Image.alpha_composite(background, image5).save(temp_path)

            Xcenter = youtube.width / 2
            Ycenter = youtube.height / 2
            x1 = Xcenter - 250
            y1 = Ycenter - 250
            x2 = Xcenter + 250
            y2 = Ycenter + 250
            logo = youtube.crop((x1, y1, x2, y2))
            logo.thumbnail((520, 520), Image.LANCZOS)
            logo.save(chop_path)
            if not os.path.isfile(cropped_path):
                im = Image.open(chop_path).convert("RGBA")
                add_corners(im)
                im.save(cropped_path)

            crop_img = Image.open(cropped_path)
            logo = crop_img.convert("RGBA")
            logo.thumbnail((365, 365), Image.LANCZOS)
            width = int((1280 - 365) / 2)
            background = Image.open(temp_path)
            background.paste(logo, (width + 2, 138), mask=logo)
            background.paste(x, (710, 427), mask=x)
            background.paste(image3, (0, 0), mask=image3)

            font_path1 = "AviaxMusic/assets/font2.ttf"
            font_path2 = "AviaxMusic/assets/font.ttf"
            if not file_exists(font_path1) or not file_exists(font_path2):
                return FAILED if file_exists(FAILED) else None
            font = ImageFont.truetype(font_path1, 45)
            ImageFont.truetype(font_path1, 70)
            arial = ImageFont.truetype(font_path1, 30)
            ImageFont.truetype(font_path2, 30)
            para = textwrap.wrap(title, width=32)
            draw = ImageDraw.Draw(background)
            try:
                draw.text(
                    (450, 25),
                    f"STARTED PLAYING",
                    fill="white",
                    stroke_width=3,
                    stroke_fill="grey",
                    font=font,
                )
                if para and para[0]:
                    text_w, text_h = draw.textsize(f"{para[0]}", font=font)
                    draw.text(
                        ((1280 - text_w) / 2, 530),
                        f"{para[0]}",
                        fill="white",
                        stroke_width=1,
                        stroke_fill="white",
                        font=font,
                    )
                if len(para) > 1 and para[1]:
                    text_w, text_h = draw.textsize(f"{para[1]}", font=font)
                    draw.text(
                        ((1280 - text_w) / 2, 580),
                        f"{para[1]}",
                        fill="white",
                        stroke_width=1,
                        stroke_fill="white",
                        font=font,
                    )
            except Exception as e:
                LOGGER.error(f"Error drawing title text: {e}")
            text_w, text_h = draw.textsize(f"Duration: {duration} Mins", font=arial)
            draw.text(
                ((1280 - text_w) / 2, 660),
                f"Duration: {duration} Mins",
                fill="white",
                font=arial,
            )
            try:
                os.remove(thumb_path)
            except Exception:
                pass
            background.save(cached_path)
            return cached_path
        except Exception as e:
            LOGGER.error(f"Error composing thumbnail: {e}")
            return FAILED if file_exists(FAILED) else None
    except Exception as e:
        LOGGER.error(f"Error generating thumbnail: {e}")
        return FAILED if file_exists(FAILED) else None

async def gen_qthumb(videoid, user_id, app):
    try:
        safe_user_id = sanitize_filename(str(user_id))
        safe_videoid = sanitize_filename(str(videoid))
        cached_path = f"cache/que{safe_videoid}_{safe_user_id}.png"
        thumb_path = f"cache/thumb{safe_videoid}.png"
        chop_path = f"cache/chop{safe_videoid}.png"
        cropped_path = f"cache/cropped{safe_videoid}.png"
        temp_path = f"cache/temp{safe_videoid}.png"

        if os.path.isfile(cached_path):
            return cached_path

        # Get user profile pic or fallback
        user_image_path = await get_user_profile_pic(app, user_id)
        if not file_exists(user_image_path):
            return None

        url = f"https://www.youtube.com/watch?v={videoid}"
        try:
            results = VideosSearch(url, limit=1)
            data = (await results.next())["result"]
            if not data:
                raise Exception("No video results found.")
            result = data[0]
            title = re.sub("\W+", " ", result.get("title", "Unsupported Title")).title()
            duration = result.get("duration", "Unknown")
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        except Exception as e:
            LOGGER.error(f"Error getting video info: {e}")
            title = "Unsupported Title"
            duration = "Unknown"
            thumbnail = None

        # Download thumbnail
        if thumbnail:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(thumbnail) as resp:
                        if resp.status == 200:
                            async with aiofiles.open(thumb_path, mode="wb") as f:
                                await f.write(await resp.read())
            except Exception as e:
                LOGGER.error(f"Failed to download thumbnail: {e}")

        # Create rounded avatar (user profile or fallback)
        try:
            xy = Image.open(user_image_path)
            a = Image.new("L", [640, 640], 0)
            b = ImageDraw.Draw(a)
            b.pieslice([(0, 0), (640, 640)], 0, 360, fill=255, outline="white")
            if a.size != xy.size:
                a = a.resize(xy.size, Image.LANCZOS)
            c = np.array(xy)
            d = np.array(a)
            e = np.dstack((c, d))
            f = Image.fromarray(e)
            x = f.resize((107, 107))
        except Exception as e:
            LOGGER.error(f"Error creating avatar: {e}")
            return FAILED if file_exists(FAILED) else None

        if not os.path.isfile(thumb_path):
            LOGGER.error(f"Thumbnail image not found: {thumb_path}, using default avatar.")
            return FAILED if file_exists(FAILED) else None

        try:
            youtube = Image.open(thumb_path)
            circle_path = "AviaxMusic/assets/circle.png"
            if not file_exists(circle_path):
                return FAILED if file_exists(FAILED) else None
            bg = Image.open(circle_path)
            image1 = changeImageSize(1280, 720, youtube)
            image2 = image1.convert("RGBA")
            background = image2.filter(filter=ImageFilter.BoxBlur(30))
            enhancer = ImageEnhance.Brightness(background)
            background = enhancer.enhance(0.6)

            image3 = changeImageSize(1280, 720, bg)
            image5 = image3.convert("RGBA")
            Image.alpha_composite(background, image5).save(temp_path)

            Xcenter = youtube.width / 2
            Ycenter = youtube.height / 2
            x1 = Xcenter - 250
            y1 = Ycenter - 250
            x2 = Xcenter + 250
            y2 = Ycenter + 250
            logo = youtube.crop((x1, y1, x2, y2))
            logo.thumbnail((520, 520), Image.LANCZOS)
            logo.save(chop_path)
            if not os.path.isfile(cropped_path):
                im = Image.open(chop_path).convert("RGBA")
                add_corners(im)
                im.save(cropped_path)

            crop_img = Image.open(cropped_path)
            logo = crop_img.convert("RGBA")
            logo.thumbnail((365, 365), Image.LANCZOS)
            width = int((1280 - 365) / 2)
            background = Image.open(temp_path)
            background.paste(logo, (width + 2, 138), mask=logo)
            background.paste(x, (710, 427), mask=x)
            background.paste(image3, (0, 0), mask=image3)

            font_path1 = "AviaxMusic/assets/font2.ttf"
            font_path2 = "AviaxMusic/assets/font.ttf"
            if not file_exists(font_path1) or not file_exists(font_path2):
                return FAILED if file_exists(FAILED) else None
            font = ImageFont.truetype(font_path1, 45)
            ImageFont.truetype(font_path1, 70)
            arial = ImageFont.truetype(font_path1, 30)
            ImageFont.truetype(font_path2, 30)
            para = textwrap.wrap(title, width=32)
            draw = ImageDraw.Draw(background)
            try:
                draw.text(
                    (455, 25),
                    "ADDED TO QUEUE",
                    fill="white",
                    stroke_width=5,
                    stroke_fill="black",
                    font=font,
                )
                if para and para[0]:
                    text_w, text_h = draw.textsize(f"{para[0]}", font=font)
                    draw.text(
                        ((1280 - text_w) / 2, 530),
                        f"{para[0]}",
                        fill="white",
                        stroke_width=1,
                        stroke_fill="white",
                        font=font,
                    )
                if len(para) > 1 and para[1]:
                    text_w, text_h = draw.textsize(f"{para[1]}", font=font)
                    draw.text(
                        ((1280 - text_w) / 2, 580),
                        f"{para[1]}",
                        fill="white",
                        stroke_width=1,
                        stroke_fill="white",
                        font=font,
                    )
            except Exception as e:
                LOGGER.error(f"Error drawing title text: {e}")
            text_w, text_h = draw.textsize(f"Duration: {duration} Mins", font=arial)
            draw.text(
                ((1280 - text_w) / 2, 660),
                f"Duration: {duration} Mins",
                fill="white",
                font=arial,
            )
            try:
                os.remove(thumb_path)
            except Exception:
                pass
            background.save(cached_path)
            return cached_path
        except Exception as e:
            LOGGER.error(f"Error composing queue thumbnail: {e}")
            return FAILED if file_exists(FAILED) else None
    except Exception as e:
        LOGGER.error(f"Error generating queue thumbnail: {e}")
        return FAILED if file_exists(FAILED) else None
