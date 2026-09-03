import pytest

from parley.transports.factory import make_transport
from parley.transports.fake import FakeTransport
from parley.transports.polling import PollingTransport


def test_polling_default():
    assert isinstance(make_transport("polling"), PollingTransport)

def test_fake():
    assert isinstance(make_transport("fake"), FakeTransport)

def test_unknown_raises():
    with pytest.raises(ValueError):
        make_transport("bogus")
