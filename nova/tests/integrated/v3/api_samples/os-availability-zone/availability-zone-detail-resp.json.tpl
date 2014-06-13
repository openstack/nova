{
    "availability_zone_info": [
        {
            "hosts": {
                "consoleauth": {
                    "nova-consoleauth": {
                        "active": true,
                        "available": true,
                        "updated_at": %(timestamp_or_none)s
                    }
                },
                "cert": {
                    "nova-cert": {
                        "active": true,
                        "available": true,
                        "updated_at": %(timestamp_or_none)s
                    }
                },
                "conductor": {
                    "nova-conductor": {
                        "active": true,
                        "available": true,
                        "updated_at": %(timestamp_or_none)s
                    }
                },
                "cells": {
                    "nova-cells": {
                        "active": true,
                        "available": true,
                        "updated_at": %(timestamp_or_none)s
                    }
                },
                "scheduler": {
                    "nova-scheduler": {
                        "active": true,
                        "available": true,
                        "updated_at": %(timestamp_or_none)s
                    }
                },
                "network": {
                    "nova-network": {
                        "active": true,
                        "available": true,
                        "updated_at": %(timestamp_or_none)s
                    }
                }
            },
            "zone_name": "internal",
            "zone_state": {
                "available": true
            }
        },
        {
            "hosts": {
                "compute": {
                    "nova-compute": {
                        "active": true,
                        "available": true,
                        "updated_at": %(timestamp_or_none)s
                    }
                }
            },
            "zone_name": "nova",
            "zone_state": {
                "available": true
            }
        }
    ]
}
