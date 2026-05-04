from unittest.mock import MagicMock, patch


def test_pay_uses_explicit_card_info_over_keyring():
    from srtgo.service import payment

    rail = MagicMock()
    rail.pay_with_card.return_value = True
    reservation = MagicMock()
    card = {"number": "1", "password": "2", "birthday": "3", "expire": "4"}

    with patch.object(payment, "get_card_info") as mock_kr:
        result = payment.pay_with_saved_card(rail, reservation, card_info=card)

    mock_kr.assert_not_called()
    rail.pay_with_card.assert_called_once_with(reservation, card)
    assert result is True


def test_pay_falls_back_to_keyring_when_no_card_info():
    from srtgo.service import payment

    rail = MagicMock()
    rail.pay_with_card.return_value = True
    reservation = MagicMock()
    kr_card = {"number": "9", "password": "8", "birthday": "7", "expire": "6"}

    with patch.object(payment, "get_card_info", return_value=kr_card) as mock_kr:
        result = payment.pay_with_saved_card(rail, reservation)

    mock_kr.assert_called_once()
    rail.pay_with_card.assert_called_once_with(reservation, kr_card)
    assert result is True


def test_pay_returns_false_when_no_card_anywhere():
    from srtgo.service import payment

    rail = MagicMock()
    reservation = MagicMock()

    with patch.object(payment, "get_card_info", return_value=None):
        result = payment.pay_with_saved_card(rail, reservation)

    assert result is False
    rail.pay_with_card.assert_not_called()
