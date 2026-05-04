from unittest.mock import patch, MagicMock

import pytest


def test_create_rail_uses_explicit_credentials_over_keyring():
    """credentials 인자가 주어지면 keyring을 호출하지 않는다."""
    from srtgo.service import auth

    with patch.object(auth, "get_rail_credential") as mock_kr, \
         patch("srtgo.rail.srt.client.SRT") as mock_srt:
        mock_srt.return_value = MagicMock()
        rail = auth.create_rail("SRT", credentials={"id": "u1", "pw": "p1"})

    mock_kr.assert_not_called()
    mock_srt.assert_called_once_with("u1", "p1", verbose=False)
    assert rail is mock_srt.return_value


def test_create_rail_falls_back_to_keyring_when_no_credentials():
    """credentials=None이면 기존대로 keyring에서 읽는다."""
    from srtgo.service import auth

    with patch.object(auth, "get_rail_credential", return_value=("k_id", "k_pw")) as mock_kr, \
         patch("srtgo.rail.srt.client.SRT") as mock_srt:
        mock_srt.return_value = MagicMock()
        auth.create_rail("SRT")

    mock_kr.assert_called_once_with("SRT")
    mock_srt.assert_called_once_with("k_id", "k_pw", verbose=False)


def test_create_rail_raises_when_credentials_missing():
    from srtgo.service import auth

    with patch.object(auth, "get_rail_credential", return_value=(None, None)):
        with pytest.raises(ValueError, match="자격증명"):
            auth.create_rail("SRT")
