#!/usr/bin/env python
try:
    from nova.vcsversion import version_info
except ImportError:
    version_info = {'branch_nick': u'LOCALBRANCH',
                    'revision_id': 'LOCALREVISION',
                    'revno': 0}

NOVA_VERSION = ['2011', '1']
YEAR, COUNT = NOVA_VERSION

FINAL = False   # This becomes true at Release Candidate time


def canonical_version_string():
    return '.'.join([YEAR, COUNT])


def version_string():
    if FINAL:
        return canonical_version_string()
    else:
        return '%s-dev' % (canonical_version_string(),)


def vcs_version_string():
    return "%s:%s" % (version_info['branch_nick'], version_info['revision_id'])


def version_string_with_vcs():
    return "%s-%s" % (canonical_version_string(), vcs_version_string())
