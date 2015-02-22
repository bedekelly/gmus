import subprocess
import sys

cmd = 'find /home/bede -name *.mp3'
bytes_ = subprocess.check_output(cmd.split())
text = bytes_.decode(sys.stdout.encoding)
mp3files = text.split("\n")
