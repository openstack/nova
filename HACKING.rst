Nova Style Commandments
=======================

- Step 1: Read the OpenStack Style Commandments
  https://github.com/openstack-dev/hacking/blob/master/HACKING.rst
- Step 2: Read on

Nova Specific Commandments
---------------------------

- ``nova.db`` imports are not allowed in ``nova/virt/*``
- [N309] no db session in public API methods (disabled)
  This enforces a guideline defined in ``nova.openstack.common.db.sqlalchemy.session``
- [N310] timeutils.utcnow() wrapper must be used instead of direct calls to
  datetime.datetime.utcnow() to make it easy to override its return value in tests

Creating Unit Tests
-------------------
For every new feature, unit tests should be created that both test and
(implicitly) document the usage of said feature. If submitting a patch for a
bug that had no unit test, a new passing unit test should be added. If a
submitted bug fix does have a unit test, be sure to add a new one that fails
without the patch and passes with the patch.

For more information on creating unit tests and utilizing the testing
infrastructure in OpenStack Nova, please read ``nova/tests/README.rst``.


Running Tests
-------------
The testing system is based on a combination of tox and testr. The canonical
approach to running tests is to simply run the command ``tox``. This will
create virtual environments, populate them with dependencies and run all of
the tests that OpenStack CI systems run. Behind the scenes, tox is running
``testr run --parallel``, but is set up such that you can supply any additional
testr arguments that are needed to tox. For example, you can run:
``tox -- --analyze-isolation`` to cause tox to tell testr to add
--analyze-isolation to its argument list.

It is also possible to run the tests inside of a virtual environment
you have created, or it is possible that you have all of the dependencies
installed locally already. In this case, you can interact with the testr
command directly. Running ``testr run`` will run the entire test suite. ``testr
run --parallel`` will run it in parallel (this is the default incantation tox
uses.) More information about testr can be found at:
http://wiki.openstack.org/testr

Building Docs
-------------
Normal Sphinx docs can be built via the setuptools ``build_sphinx`` command. To
do this via ``tox``, simply run ``tox -evenv -- python setup.py build_sphinx``,
which will cause a virtualenv with all of the needed dependencies to be
created and then inside of the virtualenv, the docs will be created and
put into doc/build/html.

If you'd like a PDF of the documentation, you'll need LaTeX installed, and
additionally some fonts. On Ubuntu systems, you can get what you need with::

    apt-get install texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended

Then run ``build_sphinx_latex``, change to the build dir and run ``make``.
Like so::

    tox -evenv -- python setup.py build_sphinx_latex
    cd build/sphinx/latex
    make

You should wind up with a PDF - Nova.pdf.
