from gmusicapi import Mobileclient
from player import get_device_id
from getpass import getpass

print("Loading client")
id = get_device_id()
api = Mobileclient()
email = "bedekelly97"
password = getpass()
print("Logging in")
api.login(email, password, id)
print(dir(api))

playlists = api.get_all_user_playlist_contents()
