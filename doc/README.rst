OpenStack Nova Documentation README
===================================
Included documents:

- developer reference guide(devref)
- man pages


Building the docs
-----------------
From the root nova director:

    python setup.py build_sphinx

Building just the man pages
---------------------------
from the root nova director:

    python setup.py build_sphinx -b man


Installing the man pages
-------------------------
After building the man pages, they can be found in ``doc/build/man/``.
You can install the man page onto your system by following the following steps:

Example for ``nova-manage``::
    # mkdir /usr/local/man/man1
    # install -g 0 -o 0 -m 0644 doc/build/man/nova-manage.1  /usr/local/man/man1/nova-manage.1
    # gzip /usr/local/man/man1/nova-manage.1
    # man nova-manage
