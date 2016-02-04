# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Super simple fake memcache client."""

import copy

from oslo_cache import core as cache
from oslo_config import cfg

from nova.i18n import _


# NOTE(dims): There are many copies of memcache_opts with memcached_servers
# in various projects as this used to be in a copy of memory_cache.py
# Since we are making a change in just our copy, oslo-config-generator fails
# with cfg.DuplicateOptError unless we override the comparison check
class _DeprecatedListOpt(cfg.ListOpt):
    def __ne__(self, another):
        self_dict = copy.deepcopy(vars(self))
        another_dict = copy.deepcopy(vars(another))
        self_dict.pop('help')
        self_dict.pop('deprecated_for_removal')
        another_dict.pop('help')
        another_dict.pop('deprecated_for_removal')
        return self_dict != another_dict


memcache_opts = [
    _DeprecatedListOpt('memcached_servers',
                       help='DEPRECATED: Memcached servers or None for in '
                            'process cache. "memcached_servers" opt is '
                            'deprecated in Mitaka. In Newton release '
                            'oslo.cache config options should be used as '
                            'this option will be removed. Please add a '
                            '[cache] group in your nova.conf file and '
                            'add "enable" and "memcache_servers" option in '
                            'this section.',
                       deprecated_for_removal=True),
]

CONF = cfg.CONF
CONF.register_opts(memcache_opts)

WEEK = 604800


def list_opts():
    """Entry point for oslo-config-generator."""
    return [(None, copy.deepcopy(memcache_opts))]


def get_memcached_client(expiration_time=0):
    """Used ONLY when memcached is explicitly needed."""
    # If the operator uses the old style [DEFAULT]/memcached_servers
    # then we just respect that setting
    if CONF.memcached_servers:
        return CacheClient(
                _get_custom_cache_region(expiration_time=expiration_time,
                                         backend='dogpile.cache.memcached',
                                         url=CONF.memcached_servers))
    # If the operator still uses the new style [cache]/memcache_servers
    # and has [cache]/enabled flag on then we let oslo_cache configure
    # the region from the configuration settings
    elif CONF.cache.enabled and CONF.cache.memcache_servers:
        return CacheClient(
                _get_default_cache_region(expiration_time=expiration_time))
    raise RuntimeError(_('memcached_servers not defined'))


def get_client(expiration_time=0):
    """Used to get a caching client."""
    # If the operator still uses the old style [DEFAULT]/memcached_servers
    # then we just respect that setting
    if CONF.memcached_servers:
        return CacheClient(
                _get_custom_cache_region(expiration_time=expiration_time,
                                         backend='dogpile.cache.memcached',
                                         url=CONF.memcached_servers))
    # If the operator has [cache]/enabled flag on then we let oslo_cache
    # configure the region from configuration settings.
    elif CONF.cache.enabled:
        return CacheClient(
                _get_default_cache_region(expiration_time=expiration_time))
    # If [cache]/enabled flag is off and [DEFAULT]/memcached_servers is
    # absent we use the dictionary backend
    return CacheClient(
            _get_custom_cache_region(expiration_time=expiration_time,
                                     backend='oslo_cache.dict'))


def _get_default_cache_region(expiration_time):
    region = cache.create_region()
    if expiration_time != 0:
        CONF.cache.expiration_time = expiration_time
    cache.configure_cache_region(CONF, region)
    return region


def _get_custom_cache_region(expiration_time=WEEK,
                             backend=None,
                             url=None):
    """Create instance of oslo_cache client.

    For backends you can pass specific parameters by kwargs.
    For 'dogpile.cache.memcached' backend 'url' parameter must be specified.

    :param backend: backend name
    :param expiration_time: interval in seconds to indicate maximum
        time-to-live value for each key
    :param url: memcached url(s)
    """

    region = cache.create_region()
    region_params = {}
    if expiration_time != 0:
        region_params['expiration_time'] = expiration_time

    if backend == 'oslo_cache.dict':
        region_params['arguments'] = {'expiration_time': expiration_time}
    elif backend == 'dogpile.cache.memcached':
        region_params['arguments'] = {'url': url}
    else:
        raise RuntimeError(_('old style configuration can use '
                             'only dictionary or memcached backends'))

    region.configure(backend, **region_params)
    return region


class CacheClient(object):
    """Replicates a tiny subset of memcached client interface."""

    def __init__(self, region):
        self.region = region

    def get(self, key):
        value = self.region.get(key)
        if value == cache.NO_VALUE:
            return None
        return value

    def get_or_create(self, key, creator):
        return self.region.get_or_create(key, creator)

    def set(self, key, value):
        return self.region.set(key, value)

    def add(self, key, value):
        return self.region.get_or_create(key, lambda: value)

    def delete(self, key):
        return self.region.delete(key)

    def get_multi(self, keys):
        values = self.region.get_multi(keys)
        return [None if value is cache.NO_VALUE else value for value in
                values]

    def delete_multi(self, keys):
        return self.region.delete_multi(keys)
