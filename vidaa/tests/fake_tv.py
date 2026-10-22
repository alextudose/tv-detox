"""A stand-in for the TV's MQTT broker with the same contract as Sidee's
MqttSession: publish/subscribe/messages/wait_for. Replies are only delivered
on topics the client subscribed to, like the real broker."""
import time

CLIENT = "aa:bb:cc:dd:ee:ff$his$a1b2c3_vidaacommon_001"
MOBILE = f"/remoteapp/mobile/{CLIENT}/"


class FakeTVSession:
    def __init__(self, replies=None):
        self.client_id = CLIENT
        self.topics = {
            "ui": f"/remoteapp/tv/ui_service/{CLIENT}/",
            "platform": f"/remoteapp/tv/platform_service/{CLIENT}/",
            "mobile": MOBILE,
            "broadcast": "/remoteapp/mobile/broadcast/",
            "applist_reply": MOBILE + "ui_service/data/applist",
            "token_reply": MOBILE + "platform_service/data/tokenissuance",
        }
        # action topic suffix -> list of (reply topic, payload)
        self.replies = replies or {}
        self.subscribed: set[str] = set()
        self.published: list[tuple[str, str]] = []
        self.messages: list[tuple[str, str]] = []

    def subscribe(self, topics):
        self.subscribed.update(topics)

    def publish(self, topic, payload=""):
        self.published.append((topic, payload))
        for suffix, answers in self.replies.items():
            if topic.endswith(suffix):
                for reply_topic, reply in answers:
                    if reply_topic in self.subscribed:
                        self.messages.append((reply_topic, reply))

    def wait_for(self, suffix, timeout, since=0):
        for topic, payload in self.messages[since:]:
            if topic.endswith(suffix):
                return payload
        time.sleep(0)  # never block in tests
        return None


def runner_for(session):
    """Same shape as sidee.client.run_with_session: op(sess, topics) -> (result, session)."""
    def run(op, host=None):
        return op(session, session.topics), None
    return run
