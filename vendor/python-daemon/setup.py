# -*- coding: utf-8 -*-

# setup.py
# Part of python-daemon, an implementation of PEP 3143.
#
# Copyright © 2008–2010 Ben Finney <ben+python@benfinney.id.au>
# Copyright © 2008 Robert Niederreiter, Jens Klein
#
# This is free software: you may copy, modify, and/or distribute this work
# under the terms of the Python Software Foundation License, version 2 or
# later as published by the Python Software Foundation.
# No warranty expressed or implied. See the file LICENSE.PSF-2 for details.

""" Distribution setup for python-daemon library.
    """

import textwrap
from setuptools import setup, find_packages

distribution_name = "python-daemon"
main_module_name = 'daemon'
main_module = __import__(main_module_name, fromlist=['version'])
version = main_module.version

short_description, long_description = (
    textwrap.dedent(d).strip()
    for d in main_module.__doc__.split(u'\n\n', 1)
    )


setup(
    name=distribution_name,
    version=version.version,
    packages=find_packages(exclude=["test"]),

    # setuptools metadata
    zip_safe=False,
    test_suite="test.suite",
    tests_require=[
        "MiniMock >=1.2.2",
        ],
    install_requires=[
        "setuptools",
        "lockfile >=0.7",
        ],

    # PyPI metadata
    author=version.author_name,
    author_email=version.author_email,
    description=short_description,
    license=version.license,
    keywords=u"daemon fork unix".split(),
    url=main_module._url,
    long_description=long_description,
    classifiers=[
        # Reference: http://pypi.python.org/pypi?%3Aaction=list_classifiers
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: Python Software Foundation License",
        "Operating System :: POSIX",
        "Programming Language :: Python",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        ],
    )
