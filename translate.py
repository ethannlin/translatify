import syncedlyrics as sl
import lyricsgenius as lg
import re
from datetime import datetime
import threading
import html
from getkey import getkey, key
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import credentials

UPDATE_SONG_INFO_INTERVAL = 1 # Interval to update song info in seconds

# Create Spotify OAuth object
def create_spotify_oauth():
    return SpotifyOAuth(
        client_id=spotify_client_id,
        client_secret=spotify_client_secret,
        redirect_uri=spotify_redirect_uri,
        scope=scope
    )

# Display the current verse to the console
def display_verse():
    global parsed_lyrics, timestamps_seconds, current_progress, paused, current_verse, times, verse_counter, new_song

    if(paused):
        previous_verse = current_verse
        current_verse =f"{song_title} by {artist_name} is paused"
        if((previous_verse != current_verse) and (current_verse != None) and (current_verse != " ")):
            print(f"\n{current_verse}\n")
        return
    
    # Find the nearest timestamp to the current timestamp
    def find_nearest_time(current_progress, timestamps_seconds, times):
        filtered_timestamps = list(filter(lambda x: timestamps_seconds[times.index(x)] <= current_progress, times)) # Filter out timestamps that are greater than current timestamp
        if not filtered_timestamps:
            index = times[0]
        else:
            index = filtered_timestamps[-1]
        return index
    
    if(parsing_in_progress_event.is_set()):
        return
    elif(times == "TypeError" or times == [] or parsed_lyrics == {}):
        previous_verse = current_verse
        current_verse = f"\nNo lyrics found for {song_title} by {artist_name}"
        if((previous_verse != current_verse)):
            print(f"\nNo lyrics found for {song_title} by {artist_name}")
        return
    else:
        previous_timestamp = verse_counter

        verse_counter = find_nearest_time(current_progress, timestamps_seconds, times)
        current_verse = parsed_lyrics[verse_counter]
        if((previous_timestamp != verse_counter) and (current_verse != None) and (current_verse != " ")):
            if(new_song):
                print(f"\nNow playing: {song_title} by {artist_name}\n")
                new_song = False
            if(translate):
                translated_verse = translate_lyrics('en', current_verse)
                print(current_verse, '->', translated_verse)
            else:
                print(current_verse)
            if(current_progress >= timestamps_seconds[-1]):
                print(f"\nEnd of lyrics for {song_title} by {artist_name}")

            lyrics_verse_event.set()

# Get the current song info
def get_current_song_info():
    global sp
    try:
        current = sp.currently_playing()
    except spotipy.exceptions.SpotifyException:
        oauth_object = create_spotify_oauth()
        token_info = oauth_object.get_access_token()
        token = token_info['access_token']

        sp = spotipy.Spotify(auth=token)
        current = sp.currently_playing()

    # Check if there is a current track playing
    if current is None or current['item'] is None:
        # current['item'] is initially None when user changes song
        return None
    
    # Get track info
    artist_name = current['item']['album']['artists'][0]['name']
    song_title = current['item']['name']
    is_playing = current['is_playing']
    progress_ms = current['progress_ms']

    # convert progress into minute and seconds
    progress_sec = progress_ms // 1000
    progress_min = progress_sec // 60
    progress_sec = progress_sec % 60 # Get remainding seconds after converting to minutes

    return {
        'artist_name': artist_name,
        'song_title': song_title,
        'is_playing': is_playing,
        'progress_sec': progress_sec,
        'progress_min': progress_min
    }

# Updates the song info
def update_song_info():
    while True:
        global song_title, artist_name, current_progress, paused
        song_title, artist_name, current_progress, paused = get_song_info()
        time.sleep(UPDATE_SONG_INFO_INTERVAL)

        if(stop_thread_event.is_set()):
            break

# Get the song info
def get_song_info():
    global song_title, artist_name, current_progress, paused

    song_info = get_current_song_info()

    if song_info is None:
        song_title = artist_name = current_progress = paused = None
    else:
        previous_song = song_title

        song_title = song_info['song_title']
        artist_name = song_info['artist_name']
        current_progress = song_info['progress_sec'] + song_info['progress_min'] * 60
        paused = not song_info['is_playing']

        if((previous_song != song_title) and (song_title != None) and (song_title != " ")):
            update_song_event.set()
            parsing_in_progress_event.set()

    update_event.set()

    return song_title, artist_name, current_progress, paused

# Update the lyrics 
def update_lyrics(song_title, artist_name):
    global parsed_lyrics, timestamps_seconds, times, new_song

    # Parse the lyrics into a dictionary of timestamps and lyrics + array of timestamps
    def parse_lyrics(lyrics):
        lines = lyrics.split('\n')
        parsed_lyrics = {} # Dictionary of timestamps and lyrics
        timestamps = [] 

        for line in lines:
            parsed_line = parse_line(line)
            if parsed_line and len(parsed_line) == 2:
                timestamp, verse = parsed_line
                parsed_lyrics[timestamp] = verse
                timestamps.append(timestamp)
        return parsed_lyrics, timestamps
    
    # Parse the line based on the regex pattern
    def parse_line(line):
        pattern = r'\[(\d+:\d+.\d+)\](.+)' # Regex pattern to match timestamps followed by lyrics
        match = re.match(pattern, line)
        if match:
            timestamp = match.group(1)
            verse = match.group(2).strip()
            return timestamp, verse
        else:
            return None
    
    # Convert the timestamps array into seconds
    def convert_to_seconds(timestamps):
        total_seconds = []
        for time in timestamps:
            time_obj = datetime.strptime(time, "%M:%S.%f")
            seconds = time_obj.minute * 60 + time_obj.second + time_obj.microsecond / 1000000
            total_seconds.append(seconds)
        return total_seconds
    
    if(update_song_event.is_set()):
        # If song has changed, update the lyrics
        update_song_event.clear()
        new_song = True
        
        # Search for lyrics in musixmatch first
        # search_term = "{}, providers=['musixmatch']".format(song_title)
        # lyrics = sl.search(search_term)
        # if(lyrics is None):
        search_term = "{} {}".format(song_title, artist_name)
        lyrics = sl.search(search_term)

        if(lyrics is not None):
            parsed_lyrics, times = parse_lyrics(lyrics)
            timestamps_seconds = convert_to_seconds(times)
        
        parsing_in_progress_event.clear()

    update_event.wait() # Wait for the variables to update
    update_event.clear() # Clear the event

# Update the display of what is currently playing to the console
def update_display():
    global current_verse
    while True:
        update_lyrics(song_title, artist_name)

        if(song_title is None):
            lyrics_verse_event.set()
            previous_verse = current_verse
            current_verse = "No song playing"
            if((previous_verse != current_verse) and (current_verse != None) and (current_verse != " ")):
                print(current_verse)
        else:
            display_verse()

        if(stop_thread_event.is_set()):
            break

# Translate the lyrics
def translate_lyrics(target: str, text: str) -> dict:

    from google.cloud import translate_v2 as translate
    translate_client = translate.Client()

    if isinstance(text, bytes):
        text = text.decode("utf-8")
    
    result = translate_client.translate(text, target_language=target)

    # print("Text: {}".format(result['input']))
    # print("Translation: {}".format(result['translatedText']))
    # print("Detected source language: {}".format(result['detectedSourceLanguage']))

    return html.unescape(result['translatedText'])


if __name__ == "__main__":
    # Global variables
    song_title = ""
    artist_name = ""
    current_progress = 0
    paused = False
    new_song = False
    translate = False
    current_verse = ""
    verse_counter = 0

    parsed_lyrics = {}
    times = []
    timestamps_seconds = []

    # Credentials for Spotify and Genius
    credentials = credentials.SetCredentials()

    spotify_client_id = credentials.client_id
    spotify_client_secret = credentials.client_secret
    spotify_redirect_uri = credentials.redirect_uri
    genius_key = credentials.genius_key
    scope = 'user-read-playback-state'

    # Authorization
    oauth_object = create_spotify_oauth()
    token_info = oauth_object.get_access_token()
    token = token_info['access_token']

    # spotify object to access API
    sp = spotipy.Spotify(auth=token)

    # genius object to access API
    gs = lg.Genius(genius_key)

    update_event = threading.Event() # Event to signal update
    update_song_event = threading.Event() # Event to signal song change
    parsing_in_progress_event = threading.Event() # Event to signal parsing in progress
    lyrics_verse_event = threading.Event() # Event to signal verse change
    stop_thread_event = threading.Event() # Event to signal stop thread

    num = int(input("Press 1 for lyric sync translation or 2 for plain lyric translation: ").strip())
    if(num == 1):

        # Updates track infos in a separate thread
        update_song_thread = threading.Thread(target=update_song_info)
        update_song_thread.start()

        # Updates display in a separate thread
        update_display_thread = threading.Thread(target=update_display)
        update_display_thread.start()

        # Wait for the lyrics to update before displaying a new verse
        while True:

            var = getkey()

            if(var == key.ESC):
                # Killing the threads
                stop_thread_event.set()
                update_event.set()
                lyrics_verse_event.set()

                update_song_thread.join()
                update_display_thread.join()
                break
            elif(var == key.T):
                translate = not translate
            
            # Runs in parallel with var = getkey()
            lyrics_verse_event.wait()
            lyrics_verse_event.clear()
    elif(num == 2):

        # Updates track infos in a separate thread
        update_song_thread = threading.Thread(target=update_song_info)
        update_song_thread.start()

        while True:

            # Blocks until a key is pressed
            print("Press enter to update lyrics for a new song or esc to exit")
            var = getkey()

            if(var == key.ESC):
                # Killing the threads
                stop_thread_event.set()
                update_song_thread.join()
                break
            
            if(update_song_event.is_set()):
                update_song_event.clear()
                song = gs.search_song(title=song_title, artist=artist_name)
            
                if((song is None)):
                    print(f"\nNo lyrics found for {song_title} by {artist_name}")
                else:
                    print(f"\n{song.lyrics}")
