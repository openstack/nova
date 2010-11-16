=================
Building the docs
=================

It is really easy. You'll need sphinx (the python one) and if you are using the virtualenv you'll need to install it in the virtualenv specifically so that it can load the nova modules.


Use `make`
==========

Just type make::

  % make

Look in the Makefile for more targets.


Manually
========

  1. Generate the code.rst file so that Sphinx will pull in our docstrings::
     
      % ./generate_autodoc_index.sh > source/code.rst

  2. Run `sphinx_build`::

      % sphinx-build -b html source build/html


The docs have been built
========================

Check out the `build` directory to find them. Yay!
