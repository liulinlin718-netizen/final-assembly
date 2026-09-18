class AssemblyError(Exception):
    def __init__(self, code, message, location=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.location = location

    def as_dict(self):
        return {"code": self.code, "message": self.message, "location": self.location}
