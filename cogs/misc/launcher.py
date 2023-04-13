"""
THIS FILE IS USED TO GENERATE HONFIGURATOR.EXE with pyinstaller
"""
import subprocess as sp
python = sp.getoutput('where python').split("\n")[0]
sp.Popen([python,'main.py'])