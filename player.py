#!/usr/bin/env python2
import os
import gi
import sys
import glib
import thread
import random
import readline
import gmusicapi
import unicodedata
from time import sleep
from getpass import getpass

gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst

GObject.threads_init()
glib.threads_init()
Gst.init(None)

MESSAGE_TIMEOUT = 3  # seconds

def strip_accents(s):
    nrm = ''.join(c for c in unicodedata.normalize('NFD', s) 
        if unicodedata.category(c) != 'Mn')
    return nrm

class GetchUnix:
    """Implements getch for unix systems. Thanks StackOverflow."""
    def __init__(self):
        import tty, sys

    def __call__(self):
        import sys, tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch


class StreamPlayer:
    """Handles the control of playbin2 from the Gst library."""
    def __init__(self, main_player):
        self._player = Gst.ElementFactory.make("playbin")  # "player" or None
        # self.playing = False
        # self.stop()

    def change_song(self, URI):
        self.stop()
        self._player.set_property('uri', URI)
        self.play()

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


def notify(txt):
    print(txt)


def term_width():
    import os
    rows, columns = os.popen('stty size', 'r').read().split()
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
        with open("device_id", "w") as id_file:
            id_file.write(str(device['id']))


class TextMenu:
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
            except ValueError:
                continue


class Player:
    def __init__(self, username, password):
        self.device_id = get_device_id(username, password)
        self.username = username
        self.password = password
        self.api = gmusicapi.Mobileclient()
        self.logged_in = self.api_login()
        self.stream_player = StreamPlayer(self)
        self.stream_player.play()
        self.paused = False
        self.playlist = []
        self.pl_pos = 0
        if self.logged_in:
            print("Logged in successfully!")
        else:
            print("Login failed.")
            quit()
        self.get_random_song()

    def player_thread(self):
        bus = self.stream_player._player.get_bus()
        try:
            bus.add_signal_watch()
            bus.connect("message", self.handle_song_end)
        except:
            print("Big thing")
        glib.MainLoop().run()

    def beginloop(self):
        self.play_song()
        thread.start_new_thread(self.player_thread, ())
        
        while True:
            os.system('setterm -cursor off')
            self.display_song()
            user_key = getch()
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
                break
            elif user_key == "a":
                self.search_library("add")
            elif user_key == "s":
                self.search_library("play")
            elif user_key == "c":
                self.clear_playlist()


    def clear_playlist(self):
        self.playlist = [self.song]
        self.pl_pos = 0

    def handle_song_end(self, bus, message):
        if message.type == Gst.MessageType.EOS:
            self.next_song()
            self.display_song()  # refresh

    def next_song(self):
        self.pl_pos += 1
        try:
            self.song = self.playlist[self.pl_pos]
            self.play_song()
        except IndexError:
            self.pl_pos -= 1

    def previous_song(self):
        if self.pl_pos > 0:
            self.pl_pos -= 1
            self.song = self.playlist[self.pl_pos]
            self.play_song()

    def search_library(self, action="play"):
        try:
            # Screw x-compatibility.
            os.system('setterm -cursor on')
            search_text = raw_input("\nSearch: ")
            os.system('setterm -cursor off')
        except (EOFError, KeyboardInterrupt):
            return
        matching_songs = []
        for song in self.api.get_all_songs():
            if any([search_text.lower() in song['title'].lower(),
                   search_text.lower() in song['artist'].lower(),
                   # search_text.lower() in song['album'].lower()s
                   ]):
                matching_songs.append(song)
                
        if not matching_songs:
            sys.stdout.write("\rNo results found.      ")
            sys.stdout.flush()
            sleep(MESSAGE_TIMEOUT)
            return
        self.playlist.append(TextMenu(matching_songs).show())
        if action == "play":
            self.song = self.playlist[-1]
            self.pl_pos = len(self.playlist) - 1
            self.play_song()
        # self.song = matching_songs[1]
        # self.play_song()

    def search_all_access(self):
        try:
            # Screw x-compatibility.
            os.system('setterm -cursor on')
            search_text = raw_input("\nSearch: ")
            os.system('setterm -cursor off')
        except (EOFError, KeyboardInterrupt):
            return
        matching_songs = self.api.search_all_access(search_text)
        if not matching_songs:
            sys.stdout.write("\rNo results found.      ")
            sys.stdout.flush()
            sleep(MESSAGE_TIMEOUT)
            return
        self.playlist.append(TextMenu(matching_songs).show())  # FIXME
        # self.song = matching_songs[1]
        # self.play_song()


    def display_song(self):
        if not self.paused:
            try:
                s = unicode("\r[Playing] {s[title]} by {s[artist]}".format(
                            s=self.song))
            except UnicodeEncodeError:
                global strip_accents
                # Don't remove this, I know it doesn't make sense but the code
                # breaks without it there. 
                s = "\r[Playing] {} by {}".format(
                        strip_accents(self.song['title']),
                        strip_accents(self.song['artist']))
        else:
            try:
                s = unicode("\r[Paused]  {s[title]} by {s[artist]}".format(
                        s=self.song))
            except UnicodeEncodeError:
                import unicodedata
                def strip_accents(s):
                    return ''.join(c for c in unicodedata.normalize('NFD', s) 
                        if unicodedata.category(c) != 'Mn')
                s = "\r[Paused]  {} by {}".format(
                        strip_accents(self.song['title']),
                        strip_accents(self.song['artist']))
        s += " " * (int(term_width()) - len(s) - 1)
        sys.stdout.write(s)
        sys.stdout.flush()


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


def disable_warnings():
    import requests.packages.urllib3 as urllib3
    urllib3.disable_warnings()


def main():
    disable_warnings()
    while True:
        username = raw_input("Username: ")
        # # notify("A password is required to use Google Music.")
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
    print


if __name__ == "__main__":
    # Implement single-character grabbing from stdin.
    try:
        from msvcrt import getch
    except ImportError:
        getch = GetchUnix()
    try:
        main()
    except Exception:
        os.system("setterm -cursor on")
        raise