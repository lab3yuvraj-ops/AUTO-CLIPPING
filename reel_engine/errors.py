class StageError(Exception):
    def __init__(self, message, retry=True, delay=60):
        super().__init__(message)
        self.retry = retry
        self.delay = delay


class PublishUncertain(StageError):
    def __init__(self, message):
        super().__init__(message, retry=False)


class ActionRequired(StageError):
    def __init__(self,message):
        super().__init__(message,retry=False)
