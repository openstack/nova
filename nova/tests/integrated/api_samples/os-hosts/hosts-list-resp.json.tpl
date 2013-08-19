{
    "hosts": [
        {
            "host_name": "%(host_name)s",
            "service": "compute",
            "zone": "nova"
        },
        {
            "host_name": "%(host_name)s",
            "service": "cert",
            "zone": "internal"
        },
        {
            "host_name": "%(host_name)s",
            "service": "network",
            "zone": "internal"
        },
        {
            "host_name": "%(host_name)s",
            "service": "scheduler",
            "zone": "internal"
        },
        {
            "host_name": "%(host_name)s",
            "service": "conductor",
            "zone": "internal"
        },
        {
            "host_name": "%(host_name)s",
            "service": "cells",
            "zone": "internal"
        },
        {
            "host_name": "%(host_name)s",
            "service": "consoleauth",
            "zone": "internal"
        }
    ]
}
