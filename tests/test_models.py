from matterkeep.models import Channel, Post, SyncState


def test_post_defaults():
    post = Post(
        id="p1", channel_id="c1", user_id="u1",
        message="hello", create_at=1000, update_at=1000,
        root_id=None, type="",
    )
    assert post.files == []
    assert post.reactions == []
    assert post.metadata == {}


def test_sync_state_defaults():
    state = SyncState()
    assert state.channels == {}
    assert state.last_run is None
    assert state.version == "1"


def test_channel_membership_default():
    ch = Channel(id="c1", team_id="t1", name="general", display_name="General", type="O")
    assert ch.membership == "member"
