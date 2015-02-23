#!/usr/bin/env python2
import os
import gi
import sys
import thread
import random
import readline
import gmusicapi
import unicodedata
from time import sleep
from getpass import getpass

gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst, GLib

GObject.threads_init()
GLib.threads_init()
Gst.init(None)

MESSAGE_TIMEOUT = 1.5  # seconds


class keys(object):
    UP_SONG = "up"
    DOWN_SONG = "down"
    SELECT_SONG = "enter"


def strip_accents(s):
    nrm = ''.join(c for c in unicodedata.normalize('NFD', s)
                  if unicodedata.category(c) != 'Mn')
    return nrm


def term_title(text):
    sys.stdout.write("\x1b]2;{}\x07".format(text))


def getch_unix():
    """Implements getch for unix systems. Thanks StackOverflow."""
    import termios
    import tty
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
        if (ch == chr(27)):
            next_ch = sys.stdin.read(2)[1]
            if next_ch in ["A", "D"]:
                return keys.UP_SONG
            elif next_ch in ["B", "D"]:
                return keys.DOWN_SONG
        elif ord(ch) == 13:
            return keys.SELECT_SONG
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


class StreamPlayer(object):
    """Handles the control of playbin2 from the Gst library."""
    def __init__(self):
        self._player = Gst.ElementFactory.make("playbin", "player")

    def change_song(self, URI):
        self.stop()
        self._player.set_property('uri', URI)
        self.play()

    @property
    def player(self):
        return self._player

    def play(self):
        self.playing = True
        self._player.set_state(Gst.State.PLAYING)

    def pause(self):
        self.playing = False
        self._player.set_state(Gst.State.PAUSED)

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def stop(self):
        self.playing = False
        self._player.set_state(Gst.State.NULL)


def term_width():
    _, columns = os.popen('stty size', 'r').read().split()
    return columns


def get_device_id(username, password):
    """Handles retrieving an android device ID to enable streaming."""
    if os.path.exists("./device_id"):
        with open("device_id") as id_file:
            device_id = id_file.read().strip()
        return device_id
    else:
        api = gmusicapi.Webclient()
        api.login(username, password)
        devices = api.get_registered_devices()
        for device in devices:
            if device['type'] == 'PHONE':
                return str(device['id'])[2:]


class TextMenu(object):
    def __init__(self, list_items):
        self.list_items = list_items
    def show(self):
        for i, s in enumerate(self.list_items):
            orig_data = [s['title'], s['artist'], s['album']]
            data = [str(strip_accents(tag)) for tag in orig_data]
            print("{}. {} - {} - {}".format(str(i+1), *data))
        while True:
            try:
                return self.list_items[int(raw_input("Choice: ")) - 1]
            except (ValueError, KeyboardInterrupt, EOFError):
                return


class Player(object):
    def __init__(self, username, password):
        self.device_id = get_device_id(username, password)
        self.username = username
        self.shuffle = False
        self.password = password
        self.api = gmusicapi.Mobileclient()
        self.search_mode = False
        self.logged_in = self.api_login()
        self.stream_player = StreamPlayer()
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
        self.get_random_song()

    def player_thread(self):
        bus = self.stream_player.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.handle_song_end)
        GLib.MainLoop().run()

    def beginloop(self):
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
        if user_key == " ":
            self.paused = not self.paused
            self.stream_player.toggle()
        elif user_key == "z":
            self.get_random_song()
            self.pl_pos += 1
            self.play_song()
        elif user_key == ">":
            self.next_song()
        elif user_key == "<":
            self.previous_song()
        elif user_key == "Q":
            os.system("setterm -cursor on")
            print
            quit()
        elif user_key == "a":
            self.search_library("add")
        elif user_key == "A":
            self.search_library("add", stay=True)
        elif user_key == "f":
            self.search_library("play")
        elif user_key == "F":
            self.search_library("add_all")
        elif user_key == "c":
            self.clear_playlist()
        elif user_key == "p":
            self.add_playlist()
        elif user_key == "s":
            self.toggle_shuffle()
        elif self.search_mode:
            self.search_mode_handle_input(user_key)

    def search_mode_handle_input(self, user_key):
        if user_key == keys.UP_SONG:
            self.select_previous_song()
        elif user_key == keys.DOWN_SONG:
            self.select_next_song()
        elif user_key == keys.SELECT_SONG:
            self.search_mode_handle_select()
        elif user_key in ["q", "c"]:
            self.search_mode = False

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle

    def add_playlist(self):
        pass
        # raise NotImplementedError  <- removing this for now as it confuses PyLint
        
        # playlists = self.api.get_all_playlists()
        # user_playlist_contents = self.api.get_all_user_playlist_contents()
        # pprint(user_playlist_contents)

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

    def search_mode_handle_select(self):
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
        if message.type == Gst.MessageType.EOS:
            self.next_song()
            self.update_song_display()
            if not self.search_mode:
                self.display_song()
            else:
                self.display_match()

    def next_song(self):
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
        if self.pl_pos > 0:
            self.pl_pos -= 1
            self.song = self.playlist[self.pl_pos]
            self.paused = False
            self.play_song()

    def notify(self, notification):
        sys.stdout.write(notification)
        sys.stdout.flush()
        sleep(MESSAGE_TIMEOUT)
        self.display_song()

    def search_library(self, action="play", stay=False):
        self.stay_in_search_mode = stay
        try:
            os.system('setterm -cursor on')
            search_text = raw_input("\nSearch: ")
            os.system('setterm -cursor off')
        except (EOFError, KeyboardInterrupt):
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
        def nopunc(text):
            return ''.join(i for i in text if i.isalpha())

        matching_songs = []
        common_words = {"on", "the", "in", "of", "and", "or", "a"}
        words = [nopunc(word.lower()) for word in search_text.split()
                 if word.lower() not in common_words]
        for song in self.api.get_all_songs():
            attributes = (song['album'], song['title'], song['albumArtist'],
                          song['artist'])
            attributes = [nopunc(item).lower() for item in attributes]

            if all(any([word in attr for attr in attributes])
                    for word in words):
                matching_songs.append(song)
        return matching_songs

    def update_song_display(self):
        if not self.paused:
            try:
                self.song_display = unicode(
                    "\r[Playing]{h} {s[title]} by {s[artist]} from {s[album]}".format(
                        s=self.song, h="[S]" if self.shuffle else ""))
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
        term_title(self.song_display)


    def display_song(self):
        num_spaces = (int(term_width()) - len(self.song_display) + 1)
        s = self.song_display + " " * num_spaces
        sys.stdout.write(s)
        sys.stdout.flush()

    def display_match(self):
        song = self.current_match
        result_display = " - ".join([song['title'], song['artist'], song['album']])
        player_display = self.song_display + "   ||   Search result: "
        result_no = str(self.match_pos + 1) + ". "
        s = player_display + result_no + result_display
        s += " " * (int(term_width()) - len(s) + 1)
        sys.stdout.write(s)
        sys.stdout.flush()

    @property
    def current_match(self):
        return self.matches[self.match_pos]

    def api_login(self):
        return self.api.login(self.username, self.password)

    def play_url(self, stream_url):
        self.stream_player.change_song(stream_url)
        self.stream_player.play()

    def get_random_song(self):
        all_songs = self.api.get_all_songs()
        self.song = random.choice(all_songs)
        self.playlist.append(self.song)

    def play_song(self):
        song_url = self.api.get_stream_url(self.song['id'], self.device_id)
        self.play_url(song_url)
        self.paused = False


def disable_warnings():
    import requests.packages.urllib3 as urllib3
    urllib3.disable_warnings()


def main():
    # disable_warnings()
    while True:
        username = raw_input("Username: ")
        password = getpass()
        try:
            player = Player(username, password)
            player.beginloop()
        except gmusicapi.exceptions.NotLoggedIn:
            print("Login details were incorrect or Google blocked a login " +
                  "attempt. Please check your email.")
        else:
            break
    os.system('setterm -cursor on')
    print()


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
