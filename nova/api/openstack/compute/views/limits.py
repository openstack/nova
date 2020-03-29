# Copyright 2010-2011 OpenStack Foundation
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


class ViewBuilder(object):
    """OpenStack API base limits view builder."""

    limit_names = {}

    def __init__(self):
        self.limit_names = {
            "ram": ["maxTotalRAMSize"],
            "instances": ["maxTotalInstances"],
            "cores": ["maxTotalCores"],
            "key_pairs": ["maxTotalKeypairs"],
            "floating_ips": ["maxTotalFloatingIps"],
            "metadata_items": ["maxServerMeta", "maxImageMeta"],
            "injected_files": ["maxPersonality"],
            "injected_file_content_bytes": ["maxPersonalitySize"],
            "security_groups": ["maxSecurityGroups"],
            "security_group_rules": ["maxSecurityGroupRules"],
            "server_groups": ["maxServerGroups"],
            "server_group_members": ["maxServerGroupMembers"]
    }

    def build(self, request, quotas, filtered_limits=None,
              max_image_meta=True):
        filtered_limits = filtered_limits or []
        absolute_limits = self._build_absolute_limits(
            quotas, filtered_limits,
            max_image_meta=max_image_meta)

        used_limits = self._build_used_limits(
            request, quotas, filtered_limits)

        absolute_limits.update(used_limits)
        output = {
            "limits": {
                "rate": [],
                "absolute": absolute_limits,
            },
        }

        return output

    def _build_absolute_limits(self, quotas, filtered_limits=None,
                               max_image_meta=True):
        """Builder for absolute limits

        absolute_limits should be given as a dict of limits.
        For example: {"ram": 512, "gigabytes": 1024}.

        filtered_limits is an optional list of limits to exclude from the
        result set.
        """
        absolute_limits = {k: v['limit'] for k, v in quotas.items()}
        limits = {}
        for name, value in absolute_limits.items():
            if (name in self.limit_names and
                    value is not None and name not in filtered_limits):
                for limit_name in self.limit_names[name]:
                    if not max_image_meta and limit_name == "maxImageMeta":
                        continue
                    limits[limit_name] = value
        return limits

    def _build_used_limits(self, request, quotas, filtered_limits):
        quota_map = {
            'totalRAMUsed': 'ram',
            'totalCoresUsed': 'cores',
            'totalInstancesUsed': 'instances',
            'totalFloatingIpsUsed': 'floating_ips',
            'totalSecurityGroupsUsed': 'security_groups',
            'totalServerGroupsUsed': 'server_groups',
        }
        used_limits = {}
        for display_name, key in quota_map.items():
            if (key in quotas and key not in filtered_limits):
                used_limits[display_name] = quotas[key]['in_use']

        return used_limits
