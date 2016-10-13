{
    "tenant_usage": {
        "server_usages": [
            {
                "ended_at": null,
                "flavor": "m1.tiny",
                "hours": 1.0,
                "instance_id": "%(uuid)s",
                "local_gb": 1,
                "memory_mb": 512,
                "name": "instance-2",
                "started_at": "%(strtime)s",
                "state": "active",
                "tenant_id": "6f70656e737461636b20342065766572",
                "uptime": 3600,
                "vcpus": 1
            }
        ],
        "start": "%(strtime)s",
        "stop": "%(strtime)s",
        "tenant_id": "6f70656e737461636b20342065766572",
        "total_hours": 1.0,
        "total_local_gb_usage": 1.0,
        "total_memory_mb_usage": 512.0,
        "total_vcpus_usage": 1.0
    },
    "tenant_usage_links": [
        {
            "href": "%(versioned_compute_endpoint)s/os-simple-tenant-usage/%(tenant_id)s?end=%(strtime_url)s&limit=1&marker=%(uuid)s&start=%(strtime_url)s",
            "rel": "next"
        }
    ]
}
