import gettext
import os

gettext.install('nova')

from nova import utils


def setup(app):
    print "**Autodocumenting from %s" % os.path.abspath(os.curdir)
    rv = utils.execute('./doc/generate_autodoc_index.sh')
    print rv[0]
