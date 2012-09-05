# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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
Time related utilities and helper functions.
"""

import calendar
import datetime

import iso8601


TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
PERFECT_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def isotime(at=None):
    """Stringify time in ISO 8601 format"""
    if not at:
        at = utcnow()
    str = at.strftime(TIME_FORMAT)
    tz = at.tzinfo.tzname(None) if at.tzinfo else 'UTC'
    str += ('Z' if tz == 'UTC' else tz)
    return str


def parse_isotime(timestr):
    """Parse time from ISO 8601 format"""
    try:
        return iso8601.parse_date(timestr)
    except iso8601.ParseError as e:
        raise ValueError(e.message)
    except TypeError as e:
        raise ValueError(e.message)


def strtime(at=None, fmt=PERFECT_TIME_FORMAT):
    """Returns formatted utcnow."""
    if not at:
        at = utcnow()
    return at.strftime(fmt)


def parse_strtime(timestr, fmt=PERFECT_TIME_FORMAT):
    """Turn a formatted time back into a datetime."""
    return datetime.datetime.strptime(timestr, fmt)


def normalize_time(timestamp):
    """Normalize time in arbitrary timezone to UTC"""
    offset = timestamp.utcoffset()
    return timestamp.replace(tzinfo=None) - offset if offset else timestamp


def is_older_than(before, seconds):
    """Return True if before is older than seconds."""
    return utcnow() - before > datetime.timedelta(seconds=seconds)


def utcnow_ts():
    """Timestamp version of our utcnow function."""
    return calendar.timegm(utcnow().timetuple())


def utcnow():
    """Overridable version of utils.utcnow."""
    if utcnow.override_time:
        return utcnow.override_time
    return datetime.datetime.utcnow()


utcnow.override_time = None


def set_time_override(override_time=datetime.datetime.utcnow()):
    """Override utils.utcnow to return a constant time."""
    utcnow.override_time = override_time


def advance_time_delta(timedelta):
    """Advance overridden time using a datetime.timedelta."""
    assert(not utcnow.override_time is None)
    utcnow.override_time += timedelta


def advance_time_seconds(seconds):
    """Advance overridden time by seconds."""
    advance_time_delta(datetime.timedelta(0, seconds))


def clear_time_override():
    """Remove the overridden time."""
    utcnow.override_time = None


def marshall_now(now=None):
    """Make an rpc-safe datetime with microseconds.

    Note: tzinfo is stripped, but not required for relative times."""
    if not now:
        now = utcnow()
    return dict(day=now.day, month=now.month, year=now.year, hour=now.hour,
                minute=now.minute, second=now.second,
                microsecond=now.microsecond)


def unmarshall_time(tyme):
    """Unmarshall a datetime dict."""
    return datetime.datetime(day=tyme['day'], month=tyme['month'],
                 year=tyme['year'], hour=tyme['hour'], minute=tyme['minute'],
                 second=tyme['second'], microsecond=tyme['microsecond'])
