"""Compatibility entrypoint for the isolated UID launcher."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from tracker_uid_launcher import main
if __name__=='__main__':main()
