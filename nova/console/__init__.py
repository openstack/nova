# vim: tabstop=4 shiftwidth=4 softtabstop=4

"""
:mod:`nova.console` -- Console Prxy to set up VM console access (i.e. with xvp)
=====================================================

.. automodule:: nova.console
   :platform: Unix
   :synopsis: Wrapper around console proxies such as xvp to set up
              multitenant VM console access
.. moduleauthor:: Monsyne Dragon <mdragon@rackspace.com>
"""
from nova.console.api import API
