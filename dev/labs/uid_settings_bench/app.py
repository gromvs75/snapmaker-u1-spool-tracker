"""Packaged isolated settings bench. No default user data path."""
import sys,tempfile
from tracker_uid_launcher import main
if __name__=='__main__':
    if len(sys.argv)==1:sys.argv += ['--window','--data',tempfile.mkdtemp(prefix='uid-settings-packaged-')]
    main()
