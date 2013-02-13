{
    "services": [
        {
            "binary": "nova-scheduler",
            "host": "host1",
            "state": "up",
            "status": "disabled",
            "updated_at": "%(timestamp)s",
            "zone": "internal"
        },
        {
            "binary": "nova-compute",
            "host": "host1",
            "state": "up",
            "status": "disabled",
            "updated_at": "%(timestamp)s",
            "zone": "nova"
        },
        {
            "binary": "nova-scheduler",
            "host": "host2",
            "state": "down",
            "status": "enabled",
            "updated_at": "%(timestamp)s",
            "zone": "internal"
        },
        {
            "binary": "nova-compute",
            "host": "host2",
            "state": "down",
            "status": "disabled",
            "updated_at": "%(timestamp)s",
            "zone": "nova"
        }
    ]
}
