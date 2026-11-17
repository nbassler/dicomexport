"""Keep every test away from the configuration directories of the machine running it.

dicomexport picks its configuration directory from $DICOMEXPORT_CONFIG_DIR,
~/.config/dicomexport and /etc/dicomexport before falling back to the shipped defaults
(issue #112). A developer's or a CI runner's real directory would otherwise change what the
tests export.
"""
import pytest

import dicomexport.config as config


@pytest.fixture(autouse=True)
def _no_site_config(monkeypatch, tmp_path_factory):
    nowhere = tmp_path_factory.mktemp("no_config")
    monkeypatch.delenv(config.ENV_VAR, raising=False)
    monkeypatch.setattr(config, "user_config_dir", lambda: nowhere / "user")
    monkeypatch.setattr(config, "system_config_dir", lambda: nowhere / "system")
