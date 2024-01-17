import datetime

from userlistnode import UserListNode

class UserList():

    def __init__(self):
        self.users = {UserListNode}

    def update_user(self, author_id: int, timestamp: datetime.datetime) -> None:
        self.users[author_id] = UserListNode(author_id, timestamp)

    def remove_user(self, author_id: int) -> None:
        del self.users[author_id]

    def get_user(self, author_id: int) -> UserListNode:
        return self.users[author_id] if self.has_user(author_id) else UserListNode(author_id, datetime.datetime.utcnow())

    def has_user(self, author_id: int) -> bool:
        return author_id in self.users.keys()

    def mark_as_notified(self, author_id: int) -> None:
        self.users[author_id].notify()