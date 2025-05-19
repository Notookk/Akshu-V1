# Initialize
yt = YouTubeAPI()

# Extract URL
url = await yt.url(message)
if not url:
    # Handle case when no URL is found
    pass

# Process query
video_info, error = await yt.details(url if url else " ".join(message.command[1:]))
if not video_info:
    # Handle error
    pass

# Get stream URL
stream_url, error = await yt.video(video_info['id'])
if stream_url:
    # Play the stream
    pass

# Or download
file_path, error = await yt.download(video_info['id'])
if file_path:
    # Play the downloaded file
    pass
