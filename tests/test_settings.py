"""test for settings"""

import pytest
from pydantic import ValidationError

from titiler.eopf.settings import DataStoreSettings


@pytest.mark.parametrize(
    "params,url",
    [
        ({"scheme": "s3", "host": "yeah/ye", "path": "yo"}, "s3://yeah/ye/yo"),
        ({"scheme": "s3", "host": "yeah/ye", "path": None}, "s3://yeah/ye"),
        ({"url": "s3://yeah/yo"}, "s3://yeah/yo"),
    ],
)
def test_datastore_settings(params, url):
    """Test DataStoreSettings."""
    settings = DataStoreSettings(**params)
    assert str(settings.url) == url


@pytest.mark.parametrize(
    "params",
    [
        {"scheme": "s3", "host": None, "path": "yo"},
        {"scheme": None, "host": "yeah/ye", "path": None},
        {"url": "thisisnotavalidurl", "scheme": None, "host": None, "path": None},
        {"url": None, "scheme": None, "host": None, "path": None},
    ],
)
def test_datastore_settings_error(params):
    """Missing URL or scheme/host."""
    with pytest.raises(ValidationError):
        DataStoreSettings(**params)
