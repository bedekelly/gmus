import subprocess
import sys
import os.path
from pprint import pprint

cmd = 'find /home/bede -name *.mp3'
bytes = subprocess.check_output(cmd.split())
text = bytes.decode(sys.stdout.encoding)
mp3files = text.split("\n")
