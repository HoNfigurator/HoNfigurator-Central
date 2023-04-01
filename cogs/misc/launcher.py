import subprocess as sp
python = sp.getoutput('where python').split("\n")[0]
sp.Popen([python,'main.py'])