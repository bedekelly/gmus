import gmusicapi
import unicodedata
from pprint import pprint
from getpass import getpass

def strip_accents(s):
    nrm = ''.join(c for c in unicodedata.normalize('NFD', s) 
        if unicodedata.category(c) != 'Mn')
    return nrm

api = gmusicapi.Mobileclient()
if not api.login(raw_input("Username: "), getpass()):
    quit("Login failed.")

all_songs = api.get_all_songs()


album_artists = []
artist_albums = {}
album_songs = {}

for song in all_songs:
    # Setup list of album artist names:
    if song['albumArtist'] not in album_artists:
        album_artists.append(song['albumArtist'])

    # Setup dict mapping album name to song objects
    try:
        album_songs[song['album']].append(song)
    except KeyError:
        album_songs[song['album']] = [song]

    # Setup dict mapping artist name to album names
    try:
        if song['album'] not in artist_albums[song['artist']]:
            artist_albums[song['artist']].append(song['album'])
    except KeyError:
        artist_albums[song['artist']] = [song['album']]

album_songs_printable = {}
for item in album_songs.items():
    value = [strip_accents(song['title']) for song in item[1]]
    album_songs_printable[strip_accents(item[0])] = value



for artist in album_artists:
    print(artist or "Unknown Artist")
    try:
        for album in artist_albums[artist]:
            print("    " + (album or "Unknown Album"))
            try:
                for song in album_songs[album]:
                    print("        " + (song['title'] or "Unknown Track"))
            except:
                pass
    except:
        pass
