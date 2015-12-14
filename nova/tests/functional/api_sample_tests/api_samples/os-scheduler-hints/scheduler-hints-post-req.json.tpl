{
    "server" : {
        "name" : "new-server-test",
        "imageRef" : "%(image_id)s",
        "flavorRef" : "1"
    },
    "OS-SCH-HNT:scheduler_hints": {
        "same_host": "%(uuid)s"
    }
}
