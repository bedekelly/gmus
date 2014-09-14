GMus
====

#####A seamless command-line player for Google Music and local MP3 files.

While this started off as a fork of Dan Nixon's PlayMusicCL, it ended up being almost completely different in the way it worked. All credits go to him for the initial idea though, and for the idea of using pygst (however much grief it was to port to 1.0!).

Command list:
	
	* a - Adds a file to the end of the playlist
	* s - As above, but also begins playing it. Playlist is unchanged.
	* < - Skip to previous song
	* > - Skip to next song
	* Space - Play/Pause
	* Shift+Q - Quit
	* c - Clear playlist. The current song will stay playing.
	* z - Play a random song. The playlist remains intact, and the random song is appended to the end of it.