#!/usr/bin/env python2
import os
import gi
import sys
import tty
import thread
import random
import termios
import readline
import gmusicapi
import unicodedata
from time import sleep
from getpass import getpass

# Initialise the streaming library
gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst, GLib
GObject.threads_init()
GLib.threads_init()
Gst.init(None)

# Hide warnings about insecure connections: it's an outdated API.
from requests.packages import urllib3
urllib3.disable_warnings()

# Set the time for which status messages will be displayed.
MESSAGE_TIMEOUT = 1.5  # seconds

class keys(object):
    """Enumerate the non-character key-types we need to check for."""
    UP_SONG = "up"
    DOWN_SONG = "down"
    SELECT_SONG = "enter"
    ADD_SONG = "a"
    ADD_MANY_SONGS = "A"
    ADD_PLAYLIST = "p"
    ADD_MANY_PLAYLISTS = "P"
    ADD_PLAY_SONG = "f"
    ADD_PLAY_ALL_MATCHING = "F"
    PLAY_PAUSE = " "
    PLAY_RANDOM_SONG = "z"
    TOGGLE_SHUFFLE = "s"
    SKIP_FORWARD = ">"
    SKIP_BACKWARD = "<"
    QUIT = "Q"
    CLEAR_PLAYLIST = "c"

    CHANGES_STATE = [ADD_SONG, ADD_MANY_SONGS, ADD_PLAYLIST, ADD_MANY_PLAYLISTS,
                     ADD_PLAY_SONG, ADD_PLAY_ALL_MATCHING]

    
def strip_accents(s):
    """Normalise unicode text, for compatibility with Google's search."""
    nrm = ''.join(c for c in unicodedata.normalize('NFD', s)
                  if unicodedata.category(c) != 'Mn')
    return nrm


def term_title(text):
    """Set the terminal title to 'text'."""
    sys.stdout.write("\x1b]2;{}\x07".format(text))


def getch_unix():
    """Implements getch for unix systems. Modified from a StackOverflow answer."""
    # Store the terminal's current settings.
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        # Get each character as it's typed, without needing a Return.
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)

        if ch == chr(27):
            next_ch = sys.stdin.read(2)[1]
            # Map arrow-keys to up and down commands.
            if next_ch in ["A", "D"]:
                ch = keys.UP_SONG
            elif next_ch in ["B", "C"]:
                ch = keys.DOWN_SONG
        elif ord(ch) == 13:
            return keys.SELECT_SONG
    finally:
        # Restore the initial terminal settings.
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


class StreamPlayer(object):
    """Handles the control of playbin from the Gst library."""
    def __init__(self):
        self.player = Gst.ElementFactory.make("playbin", "player")

    def change_song(self, URI):
        """Start playing the requested song."""
        self.stop()
        self.player.set_property('uri', URI)
        self.play()

    def play(self):
        self.playing = True
        self.player.set_state(Gst.State.PLAYING)

    def pause(self):
        self.playing = False
        self.player.set_state(Gst.State.PAUSED)

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def stop(self):
        self.playing = False
        self.player.set_state(Gst.State.NULL)


def term_width():
    """Return the width of the current terminal."""
    _, columns = os.popen('stty size', 'r').read().split()
    return columns


def get_device_id():
    """Retrieves the android device ID from $USER/.device_id."""
    dev_id_path = os.path.expanduser("~/.device_id")
    if os.path.exists(dev_id_path):
        # If we already have a device ID saved, return it.
        with open(dev_id_path) as id_file:
            device_id = id_file.read().strip()
        return device_id
    else:
        raise Exception("Store your device ID at ~/.device_id")


class Player(object):
    def __init__(self, username, password):
        self.device_id = get_device_id()
        self.username = username
        self.shuffle = False
        self.password = password
        self.api = gmusicapi.Mobileclient()
        self.search_mode = False
        self.logged_in = self.api_login()
        self.stream_player = StreamPlayer()
        self.display_match = self.display_song_match
        self.search_mode_type = "song"
        self.stream_player.play()
        self.paused = False
        self.playlist = []
        self.pl_pos = 0
        if self.logged_in:
            sys.stdout.write("Logged in successfully! Loading player now...")
            sys.stdout.flush()
        else:
            print("Login failed.")
            quit()
        self.add_random_song()

    def player_thread(self):
        bus = self.stream_player.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.handle_song_end)
        GLib.MainLoop().run()

    def beginloop(self):
        os.system("clear")
        self.play_song()
        thread.start_new_thread(self.player_thread, ())
        self.update_song_display()
        while True:
            os.system('setterm -cursor off')
            if not self.search_mode:
                self.display_song()
            else:
                self.display_match()
            user_key = getch()
            self.handle_input(user_key)
            os.system("clear")
            self.update_song_display()

    def handle_input(self, user_key):
        if self.search_mode_handle_input(user_key):
            return
        if user_key == keys.PLAY_PAUSE:
            self.paused = not self.paused
            self.stream_player.toggle()
        elif user_key == keys.PLAY_RANDOM_SONG:
            self.get_random_song()
            self.pl_pos += 1
            self.play_song()
        elif user_key == keys.SKIP_FORWARD:
            self.next_song()
        elif user_key == keys.SKIP_BACKWARD:
            self.previous_song()
        elif user_key == keys.QUIT:
            os.system("setterm -cursor on")
            print
            quit()
        elif user_key == keys.ADD_SONG:
            self.search_library("add")
        elif user_key == keys.ADD_MANY_SONGS:
            self.search_library("add", stay=True)
        elif user_key == keys.ADD_PLAY_SONG:
            self.search_library("play")
        elif user_key == keys.ADD_PLAY_ALL_MATCHING:
            self.search_library("add_all")
        elif user_key == keys.CLEAR_PLAYLIST:
            self.clear_playlist()
        elif user_key == keys.ADD_PLAYLIST:
            self.add_playlist()
        elif user_key == keys.TOGGLE_SHUFFLE:
            self.toggle_shuffle()

    def search_mode_handle_input(self, user_key):
        if not self.search_mode:
            # Don't handle the key if we're not in search mode.
            return False

        elif user_key in keys.CHANGES_STATE:
            # Don't allow adding songs while adding songs, etc.
            return True

        if user_key == keys.UP_SONG:
            self.select_previous_song()
        elif user_key == keys.DOWN_SONG:
            self.select_next_song()
        elif user_key == keys.SELECT_SONG:
            self.search_mode_handle_select()
        elif user_key in ["q", "c"]:
            self.search_mode = False
        else:
            return False
        return True

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle

    def enter_search_mode(self, matches, action):
        self.search_mode = True
        self.matches = matches
        self.search_mode_action = action
        self.match_pos = 0
        self.display_match()

    def select_next_song(self):
        if self.match_pos < len(self.matches) - 1:
            self.match_pos += 1
            self.display_match()

    def get_playlist_songs(match_title):
        pass

    def search_mode_handle_select(self):
        """The user just selected a song/pl, while in search mode."""
        if self.search_mode_type == "playlist":
            pl_songs = self.get_playlist_songs(self.current_match)
            self.playlist.extend(pl_songs)
            return
        # Here, we're adding a single track.
        self.playlist.append(self.current_match)
        if self.search_mode_action == "play":
            self.pl_pos = len(self.playlist) - 1
            self.song = self.playlist[-1]
            self.play_song()
        if not self.stay_in_search_mode:
            self.search_mode = False
            self.display_song()

    def select_previous_song(self):
        if self.match_pos > 0:
            self.match_pos -= 1
            self.display_match()

    def clear_playlist(self):
        self.playlist = [self.song]
        self.pl_pos = 0

    def handle_song_end(self, _, message):
        """Callback for when the currently playing song ends."""
        if message.type == Gst.MessageType.EOS:
            self.next_song()
            self.update_song_display()
            if not self.search_mode:
                self.display_song()
            else:
                self.display_match()

    def add_playlist(self):
        """Search for and add a single playlist to the main list."""
        


    def next_song(self):
        """Move to the next song in the playlist."""
        self.pl_pos += 1
        try:
            if self.shuffle:
                self.song = random.choice(self.playlist)
                self.pl_pos = self.playlist.index(self.song)
            else:
                self.song = self.playlist[self.pl_pos]
            self.play_song()
            self.paused = False
        except IndexError:
            self.pl_pos -= 1

    def previous_song(self):
        """Move to the previous song in the playlist."""
        if self.pl_pos > 0:
            self.pl_pos -= 1
            self.song = self.playlist[self.pl_pos]
            self.paused = False
            self.play_song()

    def notify(self, notification):
        """Display an important message to the user. Write a message to stdout,
        wait MESSAGE_TIMEOUT seconds, then resume normal display mode."""
        sys.stdout.write(notification)
        sys.stdout.flush()
        sleep(MESSAGE_TIMEOUT)
        self.display_song()

    def search_library(self, action="play", stay=False):
        """Search the library for a song, then execute 'action'."""
        self.stay_in_search_mode = stay
        search_text = get_search_text()
        if search_text is None:
            return
        matching_songs = self.get_search_results(search_text)
        if not matching_songs:
            self.notify("\rNo results found.")
            return
        if action == "add_all":
            self.paused = False
            self.playlist.extend(matching_songs)
        else:
            self.enter_search_mode(matching_songs, action)

    def get_search_results(self, search_text):
        """Return the list of matching songs for the given search text."""
        def nopunc(text):
            """Strip all punctuation from the search text."""
            return ''.join(i for i in text if i.isalpha())

        matching_songs = []
        common_words = {"on", "the", "in", "of", "and", "or", "a"}

        # Remove common words from the search text.
        words = [nopunc(word.lower()) for word in search_text.split()
                 if word.lower() not in common_words]

        # For each song in the library, check if there's a match.
        for song in self.api.get_all_songs():
            attributes = (song['album'], song['title'], song['albumArtist'],
                          song['artist'])
            attributes = [nopunc(item).lower() for item in attributes]

            # If every word in the search text is found somewhere in the song's
            # attributes, add the song to our list of matching songs.
            if all(any([word in attr for attr in attributes])
                    for word in words):
                matching_songs.append(song)
        return matching_songs

    def update_song_display(self):
        """Assuming we're not in search mode, update the current song display
        to reflect the currently-playing song."""
        if not self.paused:
            try:
                self.song_display = unicode(
                    "\r[Playing]{h} {s[title]} by {s[artist]} from {s[album]}"
                    "".format(s=self.song, h="[S]" if self.shuffle else ""))
            except UnicodeEncodeError:
                self.song_display = "\r[Playing]{h} {} by {}".format(
                    strip_accents(self.song['title']),
                    strip_accents(self.song['artist']),
                    h="[S]" if self.shuffle else "",)
        else:
            try:
                self.song_display = unicode(
                    "\r[Paused]{h}  {s[title]} by {s[artist]} from {s[album]}".format(
                        s=self.song,
                        h="[S]" if self.shuffle else "",))
            except UnicodeEncodeError:
                self.song_display = "\r[Paused]{h}  {} by {}".format(
                    strip_accents(self.song['title']),
                    strip_accents(self.song['artist']),
                    h="[S]" if self.shuffle else "")
        
        self.song_display = truncate_eighty(self.song_display)
        term_title(self.song_display)


    def display_song(self):
        """Display a currently-playing song in the terminal."""
        num_spaces = (int(term_width()) - len(self.song_display) + 1)
        s = self.song_display + " " * num_spaces
        sys.stdout.write(s)
        sys.stdout.flush()

    def display_song_match(self):
        """Display our current search result alongside the playing song."""
        song = self.current_match
        song_info = (song['title'], song['artist'], song['album'])
        result_display = u" - ".join(song_info)
        num = self.match_pos
        result_display = u"\nSearch result: {}. {}".format(num, result_display)
        result_display = truncate_eighty(result_display)
        player_display = self.song_display
        
        s = player_display + result_display
        s += u" " * (int(term_width()) - len(s) + 1)
        sys.stdout.write(s)
        sys.stdout.flush()

    @property
    def current_match(self):
        """Return the search-match at our current position."""
        return self.matches[self.match_pos]

    def api_login(self):
        """Login to the API with the username, password and device ID we have."""
        status = self.api.login(self.username, self.password, self.device_id)
        return status

    def play_url(self, stream_url):
        """Change the player's current song to stream_url."""
        self.stream_player.change_song(stream_url)
        self.stream_player.play()

    def add_random_song(self):
        """Adds a random song-choice to the library."""
        all_songs = self.api.get_all_songs()
        self.song = random.choice(all_songs)
        self.playlist.append(self.song)

    def play_song(self):
        """Grab a song's URL and pass it along to our player."""
        song_url = self.api.get_stream_url(self.song['id'])
        self.play_url(song_url)
        self.paused = False


def get_search_text():
    """Let the user input some text to search with."""
    os.system('setterm -cursor on')
    try:
        search_text = raw_input("\nSearch: ")
    except (EOFError, KeyboardInterrupt):
        search_text = None
    os.system('setterm -cursor off')
    return search_text


def main():
    while True:
        username = raw_input("Username: ")
        password = getpass()
        try:
            player = Player(username, password)
            player.beginloop()
        except gmusicapi.exceptions.NotLoggedIn as e:
            print("Login details were incorrect or Google blocked a login " +
                  "attempt. Please check your email.")
        else:
            break
    os.system('setterm -cursor on')
    print()


def truncate_eighty(text):
    """Truncate 'text' to 80 characters and return."""
    text = (text[:77] + "...") if len(text) > 79 else text
    return text



if __name__ == "__main__":
    try:
        from msvcrt import getch
    except ImportError:
        getch = getch_unix
    try:
        main()
    except Exception:
        os.system("setterm -cursor on")
        raise
