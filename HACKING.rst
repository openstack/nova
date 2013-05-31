Nova Style Commandments
=======================

- Step 1: Read http://www.python.org/dev/peps/pep-0008/
- Step 2: Read http://www.python.org/dev/peps/pep-0008/ again
- Step 3: Read on


General
-------
- Put two newlines between top-level code (funcs, classes, etc)
- Use only UNIX style newlines ("\n"), not Windows style ("\r\n")
- Put one newline between methods in classes and anywhere else
- Long lines should be wrapped in parentheses
  in preference to using a backslash for line continuation.
- Do not write "except:", use "except Exception:" at the very least
- Include your name with TODOs as in "#TODO(termie)"
- Do not shadow a built-in or reserved word. Example::

    def list():
        return [1, 2, 3]

    mylist = list() # BAD, shadows `list` built-in

    class Foo(object):
        def list(self):
            return [1, 2, 3]

    mylist = Foo().list() # OKAY, does not shadow built-in

- Use the "is not" operator when testing for unequal identities. Example::

    if not X is Y:  # BAD, intended behavior is ambiguous
        pass

    if X is not Y:  # OKAY, intuitive
        pass

- Use the "not in" operator for evaluating membership in a collection. Example::

    if not X in Y:  # BAD, intended behavior is ambiguous
        pass

    if X not in Y:  # OKAY, intuitive
        pass

    if not (X in Y or X in Z):  # OKAY, still better than all those 'not's
        pass


Imports
-------
- Do not import objects, only modules (*)
- Do not import more than one module per line (*)
- Do not use wildcard ``*`` import (*)
- Do not make relative imports
- Do not make new nova.db imports in nova/virt/*
- Order your imports by the full module path
- Organize your imports according to the following template

(*) exceptions are:

- imports from ``migrate`` package
- imports from ``sqlalchemy`` package
- imports from ``nova.db.sqlalchemy.session`` module
- imports from ``nova.db.sqlalchemy.migration.versioning_api`` package

Example::

  # vim: tabstop=4 shiftwidth=4 softtabstop=4
  {{stdlib imports in human alphabetical order}}
  \n
  {{third-party lib imports in human alphabetical order}}
  \n
  {{nova imports in human alphabetical order}}
  \n
  \n
  {{begin your code}}


Human Alphabetical Order Examples
---------------------------------
Example::

  import httplib
  import logging
  import random
  import StringIO
  import time
  import unittest

  import eventlet
  import webob.exc

  import nova.api.ec2
  from nova.api import openstack
  from nova.auth import users
  from nova.endpoint import cloud
  import nova.flags
  from nova import test


Docstrings
----------
Example::

  """A one line docstring looks like this and ends in a period."""


  """A multi line docstring has a one-line summary, less than 80 characters.

  Then a new paragraph after a newline that explains in more detail any
  general information about the function, class or method. Example usages
  are also great to have here if it is a complex class for function.

  When writing the docstring for a class, an extra line should be placed
  after the closing quotations. For more in-depth explanations for these
  decisions see http://www.python.org/dev/peps/pep-0257/

  If you are going to describe parameters and return values, use Sphinx, the
  appropriate syntax is as follows.

  :param foo: the foo parameter
  :param bar: the bar parameter
  :returns: return_type -- description of the return value
  :returns: description of the return value
  :raises: AttributeError, KeyError
  """


Dictionaries/Lists
------------------
If a dictionary (dict) or list object is longer than 80 characters, its items
should be split with newlines. Embedded iterables should have their items
indented. Additionally, the last item in the dictionary should have a trailing
comma. This increases readability and simplifies future diffs.

Example::

  my_dictionary = {
      "image": {
          "name": "Just a Snapshot",
          "size": 2749573,
          "properties": {
               "user_id": 12,
               "arch": "x86_64",
          },
          "things": [
              "thing_one",
              "thing_two",
          ],
          "status": "ACTIVE",
      },
  }


Calling Methods
---------------
Calls to methods 80 characters or longer should format each argument with
newlines. This is not a requirement, but a guideline::

    unnecessarily_long_function_name('string one',
                                     'string two',
                                     kwarg1=constants.ACTIVE,
                                     kwarg2=['a', 'b', 'c'])


Rather than constructing parameters inline, it is better to break things up::

    list_of_strings = [
        'what_a_long_string',
        'not as long',
    ]

    dict_of_numbers = {
        'one': 1,
        'two': 2,
        'twenty four': 24,
    }

    object_one.call_a_method('string three',
                             'string four',
                             kwarg1=list_of_strings,
                             kwarg2=dict_of_numbers)


Internationalization (i18n) Strings
-----------------------------------
In order to support multiple languages, we have a mechanism to support
automatic translations of exception and log strings.

Example::

    msg = _("An error occurred")
    raise HTTPBadRequest(explanation=msg)

If you have a variable to place within the string, first internationalize the
template string then do the replacement.

Example::

    msg = _("Missing parameter: %s") % ("flavor",)
    LOG.error(msg)

If you have multiple variables to place in the string, use keyword parameters.
This helps our translators reorder parameters when needed.

Example::

    msg = _("The server with id %(s_id)s has no key %(m_key)s")
    LOG.error(msg % {"s_id": "1234", "m_key": "imageId"})


Creating Unit Tests
-------------------
For every new feature, unit tests should be created that both test and
(implicitly) document the usage of said feature. If submitting a patch for a
bug that had no unit test, a new passing unit test should be added. If a
submitted bug fix does have a unit test, be sure to add a new one that fails
without the patch and passes with the patch.

For more information on creating unit tests and utilizing the testing
infrastructure in OpenStack Nova, please read nova/tests/README.rst.


Running Tests
-------------
The testing system is based on a combination of tox and testr. The canonical
approach to running tests is to simply run the command `tox`. This will
create virtual environments, populate them with depenedencies and run all of
the tests that OpenStack CI systems run. Behind the scenes, tox is running
`testr run --parallel`, but is set up such that you can supply any additional
testr arguments that are needed to tox. For example, you can run:
`tox -- --analyze-isolation` to cause tox to tell testr to add
--analyze-isolation to its argument list.

It is also possible to run the tests inside of a virtual environment
you have created, or it is possible that you have all of the dependencies
installed locally already. In this case, you can interact with the testr
command directly. Running `testr run` will run the entire test suite. `testr
run --parallel` will run it in parallel (this is the default incantation tox
uses.) More information about testr can be found at:
http://wiki.openstack.org/testr

Building Docs
-------------
Normal Sphinx docs can be built via the setuptools `build_sphinx` command. To
do this via `tox`, simply run `tox -evenv -- python setup.py build_sphinx`,
which will cause a virtualenv with all of the needed dependencies to be
created and then inside of the virtualenv, the docs will be created and
put into doc/build/html.

If you'd like a PDF of the documentation, you'll need LaTeX installed, and
additionally some fonts. On Ubuntu systems, you can get what you need with::

    apt-get install texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended

Then run `build_sphinx_latex`, change to the build dir and run `make`.
Like so::

    tox -evenv -- python setup.py build_sphinx_latex
    cd build/sphinx/latex
    make

You should wind up with a PDF - Nova.pdf.

openstack-common
----------------

A number of modules from openstack-common are imported into the project.

These modules are "incubating" in openstack-common and are kept in sync
with the help of openstack-common's update.py script. See:

  http://wiki.openstack.org/CommonLibrary#Incubation

The copy of the code should never be directly modified here. Please
always update openstack-common first and then run the script to copy
the changes across.

OpenStack Trademark
-------------------

OpenStack is a registered trademark of the OpenStack Foundation, and uses the
following capitalization:

   OpenStack


Commit Messages
---------------
Using a common format for commit messages will help keep our git history
readable. Follow these guidelines:

  First, provide a brief summary of 50 characters or less.  Summaries
  of greater then 72 characters will be rejected by the gate.

  The first line of the commit message should provide an accurate
  description of the change, not just a reference to a bug or
  blueprint. It must be followed by a single blank line.

  If the change relates to a specific driver (libvirt, xenapi, qpid, etc...),
  begin the first line of the commit message with the driver name, lowercased,
  followed by a colon.

  Following your brief summary, provide a more detailed description of
  the patch, manually wrapping the text at 72 characters. This
  description should provide enough detail that one does not have to
  refer to external resources to determine its high-level functionality.

  Once you use 'git review', two lines will be appended to the commit
  message: a blank line followed by a 'Change-Id'. This is important
  to correlate this commit with a specific review in Gerrit, and it
  should not be modified.

For further information on constructing high quality commit messages,
and how to split up commits into a series of changes, consult the
project wiki:

   http://wiki.openstack.org/GitCommitMessages
