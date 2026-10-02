"""Internal owned-session bootstrap; argv is passed verbatim, without a shell."""
import os
import sys

if __name__ == '__main__':
    if os.name == 'nt' or not sys.argv[1:]:
        raise SystemExit('OWNED_PROCESS_GROUP_INVALID')
    os.environ['LC_IPR_OWNED_PROCESS_GROUP'] = str(os.getpgrp())
    os.execvpe(sys.argv[1], sys.argv[1:], os.environ)
