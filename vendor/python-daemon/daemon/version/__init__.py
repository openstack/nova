# -*- coding: utf-8 -*-

# daemon/version/__init__.py
# Part of python-daemon, an implementation of PEP 3143.
#
# Copyright © 2008–2010 Ben Finney <ben+python@benfinney.id.au>
# This is free software: you may copy, modify, and/or distribute this work
# under the terms of the Python Software Foundation License, version 2 or
# later as published by the Python Software Foundation.
# No warranty expressed or implied. See the file LICENSE.PSF-2 for details.

""" Version information for the python-daemon distribution. """

from version_info import version_info

version_info['version_string'] = u"1.5.5"

version_short = u"%(version_string)s" % version_info
version_full = u"%(version_string)s.r%(revno)s" % version_info
version = version_short

author_name = u"Ben Finney"
author_email = u"ben+python@benfinney.id.au"
author = u"%(author_name)s <%(author_email)s>" % vars()

copyright_year_begin = u"2001"
date = version_info['date'].split(' ', 1)[0]
copyright_year = date.split('-')[0]
copyright_year_range = copyright_year_begin
if copyright_year > copyright_year_begin:
    copyright_year_range += u"–%(copyright_year)s" % vars()

copyright = (
    u"Copyright © %(copyright_year_range)s %(author)s and others"
    ) % vars()
license = u"PSF-2+"
