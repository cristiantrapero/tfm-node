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

    def get_messages(self):
        self.open_file('r')
        messages = self.read_from_file()
        self.close_file()
        return messages
    
    def save_message(self, sender, message):
        self.open_file('r')
        messages = self.read_from_file()
        self.close_file()
        try:
            messages = ujson.loads(messages)
        except Exception as ex:
            print(ex)
            messages = []
        time = RTC().now()
        messages.append({time : {sender.decode('utf-8') : message.decode('utf-8')}})
        self.open_file('w')
        self.write_to_file(ujson.dumps(messages))
        self.close_file()

