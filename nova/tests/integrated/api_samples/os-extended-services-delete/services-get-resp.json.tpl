{
    "services": [
        {
            "id": 1,
            "binary": "nova-scheduler",
            "host": "host1",
            "state": "up",
            "status": "disabled",
            "updated_at": "%(strtime)s",
            "zone": "internal"
        },
        {
            "id": 2,
            "binary": "nova-compute",
            "host": "host1",
            "state": "up",
            "status": "disabled",
            "updated_at": "%(strtime)s",
            "zone": "nova"
        },
        {
            "id": 3,
            "binary": "nova-scheduler",
            "host": "host2",
            "state": "down",
            "status": "enabled",
            "updated_at": "%(strtime)s",
            "zone": "internal"
        },
        {
            "id": 4,
            "binary": "nova-compute",
            "host": "host2",
            "state": "down",
            "status": "disabled",
            "updated_at": "%(strtime)s",
            "zone": "nova"
        }
    ]
}
