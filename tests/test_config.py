import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize("url", ["postgresql://localhost/app", "sqlite:///", "sqlite:///:memory:"])
def test_only_file_backed_sqlite_configuration_is_accepted(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)
