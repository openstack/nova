# Copyright 2023 SAP SE
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

from enum import auto
from enum import Enum
import logging
from typing import Union

import statsd

import nova.conf

LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF


class MetricType(Enum):
    """https://statsd.readthedocs.io/en/v4.0.1/types.html"""
    COUNTER = auto()
    TIMER = auto()
    GAUGE = auto()
    SET = auto()


_METRICS_PREFIX = "openstack.compute"
_STATSD_CLIENT = None


def _get_statsd_client():
    global _STATSD_CLIENT
    if not _STATSD_CLIENT:
        _STATSD_CLIENT = statsd.StatsClient(CONF.statsd_host,
                                            CONF.statsd_port)
    return _STATSD_CLIENT


def _send_metric(tag: str, value: Union[int, float],
                 m_type: MetricType = MetricType.GAUGE):
    client = _get_statsd_client()
    try:
        if m_type == MetricType.GAUGE:
            client.gauge(f"{_METRICS_PREFIX}.{tag}", value)
        else:
            raise NotImplementedError(m_type)
    except Exception as err:
        LOG.exception(f"Exception during metrics handling: {err}")


def gauge(tag: str, value: Union[int, float]):
    _send_metric(tag, value, MetricType.GAUGE)
