import os

from nova import utils

def setup(app):
    rootdir = os.path.abspath(app.srcdir + '/..')
    print "**Autodocumenting from %s" % rootdir
    rv = utils.execute('cd %s && ./generate_autodoc_index.sh' % rootdir)
    print rv[0]
