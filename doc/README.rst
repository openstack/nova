OpenStack Nova Documentation README
===================================
Included documents:

- developer reference guide(devref)
- man pages


Building the docs
-----------------
From the root nova directory::

  python setup.py build_sphinx

Building just the man pages
---------------------------
from the root nova directory::

  python setup.py build_sphinx -b man


Installing the man pages
-------------------------
After building the man pages, they can be found in ``doc/build/man/``.
You can install the man page onto your system by following the following steps:

Example for ``nova-scheduler``::

  mkdir /usr/local/man/man1
  install -g 0 -o 0 -m 0644 doc/build/man/nova-scheduler.1  /usr/local/man/man1/nova-scheduler.1
  gzip /usr/local/man/man1/nova-scheduler.1
  man nova-scheduler
