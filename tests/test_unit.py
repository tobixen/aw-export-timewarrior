from datetime import datetime

## TODO: work in progress

class TimewMockup:
    def __init__(self):
        self.tags = {'afk', 'lunch'}
        self.start_time = datetime(2025,5,28, 11,0,0)

    def timew_run(commands):
        command = commands[0]
        tags = commands[1:]
        if command == 'start':
            newtags = set()
            for tag in tags:
                try:
                    self.start_time = datetime.fromisoformat(tag)
                except ValueError:
                    pass
                else:
                    newtags.add(tag)

    def get_timew_info(self):
        return {
            "id": 1,
            "start": self.start_time.strftime("%Y%m%dT%H%M%SZ"),
            "start_dt": self.start_time,
            "tags": self.tags}

