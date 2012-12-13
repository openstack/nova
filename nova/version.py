# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 OpenStack LLC
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

NOVA_VENDOR = "OpenStack Foundation"
NOVA_PRODUCT = "OpenStack Nova"
NOVA_PACKAGE = None  # OS distro package version suffix
NOVA_VERSION = ['2013', '1', None]
YEAR, COUNT, REVISION = NOVA_VERSION
FINAL = False   # This becomes true at Release Candidate time

loaded = False


def _load_config():
    # Don't load in global context, since we can't assume
    # these modules are accessible when distutils uses
    # this module
    import ConfigParser

    from nova.openstack.common import cfg
    from nova.openstack.common import log as logging

    global loaded, NOVA_VENDOR, NOVA_PRODUCT, NOVA_PACKAGE
    if loaded:
        return

    loaded = True

    cfgfile = cfg.CONF.find_file("release")
    if cfgfile is None:
        return

    try:
        cfg = ConfigParser.RawConfigParser()
        cfg.read(cfgfile)

        NOVA_VENDOR = cfg.get("Nova", "vendor")
        if cfg.has_option("Nova", "vendor"):
            NOVA_VENDOR = cfg.get("Nova", "vendor")

        NOVA_PRODUCT = cfg.get("Nova", "product")
        if cfg.has_option("Nova", "product"):
            NOVA_PRODUCT = cfg.get("Nova", "product")

        NOVA_PACKAGE = cfg.get("Nova", "package")
        if cfg.has_option("Nova", "package"):
            NOVA_PACKAGE = cfg.get("Nova", "package")
    except Exception, ex:
        LOG = logging.getLogger(__name__)
        LOG.error("Failed to load %(cfgfile)s: %(ex)s" % locals())


def vendor_string():
    _load_config()

    return NOVA_VENDOR


def product_string():
    _load_config()

    return NOVA_PRODUCT


def package_string():
    _load_config()

    return NOVA_PACKAGE


def canonical_version_string():
    return '.'.join(filter(None, NOVA_VERSION))


def version_string():
    if FINAL:
        return canonical_version_string()
    else:
        return '%s-dev' % (canonical_version_string(),)


def version_string_with_package():
    if package_string() is None:
        return canonical_version_string()
    else:
        return "%s-%s" % (canonical_version_string(), package_string())
