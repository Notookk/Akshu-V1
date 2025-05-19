yt = YouTube()

# In your play command:
async def play_command(client, message):
    # Extract URL
    url = await yt.extract_url(message)
    if not url:
        await message.reply("❌ Please provide a valid YouTube URL")
        return
    
    # Process query
    video_info, error = await yt.process_query(url)
    if not video_info:
        await message.reply(f"❌ {error}")
        return
    
    # Try to stream first
    stream_url, error = await yt.get_stream_url(video_info['id'])
    if stream_url:
        # Play the stream URL
        await message.reply(f"🎧 Streaming: {video_info['title']}")
        return
    
    # Fallback to download if streaming fails
    file_path, error = await yt.download(video_info['id'])
    if file_path:
        # Play the downloaded file
        await message.reply(f"🎧 Playing: {video_info['title']}")
        return
    
    # If all fails
    await message.reply(f"❌ Failed to play: {error}")
