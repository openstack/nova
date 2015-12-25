# Copyright (c) 2012-2013 Rackspace Hosting
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

"""
Image properties filter.

Image metadata named 'hypervisor_version_requires' with a version specification
may be specified to ensure the build goes to a cell which has hypervisors of
the required version.

If either the version requirement on the image or the hypervisor capability
of the cell is not present, this filter returns without filtering out the
cells.
"""

from distutils import versionpredicate

from nova.cells import filters


class ImagePropertiesFilter(filters.BaseCellFilter):
    """Image properties filter. Works by specifying the hypervisor required in
    the image metadata and the supported hypervisor version in cell
    capabilities.
    """

    def filter_all(self, cells, filter_properties):
        """Override filter_all() which operates on the full list
        of cells...
        """
        request_spec = filter_properties.get('request_spec', {})
        image_properties = request_spec.get('image', {}).get('properties', {})
        hypervisor_version_requires = image_properties.get(
            'hypervisor_version_requires')

        if hypervisor_version_requires is None:
            return cells

        filtered_cells = []
        for cell in cells:
            version = cell.capabilities.get('prominent_hypervisor_version')
            if version:
                l = list(version)
                version = str(l[0])

            if not version or self._matches_version(version,
                                            hypervisor_version_requires):
                filtered_cells.append(cell)

        return filtered_cells

    def _matches_version(self, version, version_requires):
        predicate = versionpredicate.VersionPredicate(
                             'prop (%s)' % version_requires)
        return predicate.satisfied_by(version)
