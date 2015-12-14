{
    "server": {
        "name": "new-server-test",
        "imageRef": "%(image_id)s",
        "flavorRef": "1",
        "metadata": {
            "My Server Name": "Apache1"
        },
        "return_reservation_id": "True",
        "min_count": "%(min_count)s",
        "max_count": "%(max_count)s"
    }
}
