# Copyright 2013 Red Hat, Inc.
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

"""Provides a way to generate serializable reports

This package/module provides mechanisms for defining reports
which may then be serialized into various data types.  Each
report ( :class:`openstack.common.report.report.BasicReport` )
is composed of one or more report sections
( :class:`openstack.common.report.report.BasicSection` ),
which contain generators which generate data models
( :class:`openstack.common.report.models.base.ReportModels` ),
which are then serialized by views.
"""
