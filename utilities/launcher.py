"""
THIS FILE IS USED TO GENERATE HONFIGURATOR.EXE with pyinstaller
"""
import sys
import subprocess as sp

python = sp.getoutput('where python').split("\n")[0]
args = sys.argv[1:]  # Get the command-line arguments excluding the launcher script name
sp.Popen([python, 'main.py'] + args)  # Pass the command-line arguments to main.py