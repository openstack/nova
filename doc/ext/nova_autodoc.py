import gettext
import os

gettext.install('nova')

from nova import utils

def setup(app):
    rootdir = os.path.abspath(app.srcdir + '/..')
    print "**Autodocumenting from %s" % rootdir
    os.chdir(rootdir)
    rv = utils.execute('./generate_autodoc_index.sh')
    print rv[0]
