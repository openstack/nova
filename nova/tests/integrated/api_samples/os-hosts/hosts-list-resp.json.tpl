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
            "zone": "nova"
        },
        {
            "host_name": "%(host_name)s",
            "service": "network",
            "zone": "nova"
        },
        {
            "host_name": "%(host_name)s",
            "service": "scheduler",
            "zone": "nova"
        },
        {
	    "host_name": "%(host_name)s",
	    "service": "conductor",
	    "zone": "nova"
        }
    ]
}
