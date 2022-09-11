import ujson
from machine import RTC

class FileHandler:
    def __init__(self):
        self.file_path = '/flash/database.json'
        self.file = None

    def open_file(self, mode):
        self.file = open(self.file_path, mode)

    def close_file(self):
        self.file.close()

    def write_to_file(self, data):
        self.file.write(data)

    def read_from_file(self):
        return self.file.read()

    def database_exists(self):
        try:
            self.open_file('r')
            self.close_file()
            return True
        except OSError:
            return False

    def create_database(self):
        self.open_file('w')
        self.close_file()

    def get_messages(self):
        if self.database_exists():
            self.open_file('r')
            data = self.read_from_file()
            self.close_file()
            return ujson.loads(data)
        else:
            self.create_database()
            return []

    def save_message(self, sender, message):
        timestamp = RTC().now()
        messages = self.get_messages()
        messages.append({
            'sender': sender,
            'message': message,
            'time': timestamp
        })
        self.open_file('w')
        self.write_to_file(ujson.dumps(messages))
        self.close_file()

    def delete_messages(self):
        self.open_file('w')
        self.write_to_file(ujson.dumps([]))
        self.close_file()