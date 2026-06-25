"""Task 0004: coverage for the runner ``orderbook_delta`` WS wire path.

The ``run_intraday`` WS handler routes ``orderbook_delta`` events to
``_apply_orderbook_delta`` (the delta branch of ``_on_ws_event``, extracted to
module level so it is testable). These tests exercise it end-to-end against a
REAL ``PaperBook``:

  - the wire parse: ``price_dollars`` string -> cents (``round``, not truncate)
    and signed ``delta_fp`` -> size;
  - level add / reduce / full-removal;
  - orphan delta (market not yet snapshotted) -> book uncorrupted + WARNING;
  - malformed delta (missing/invalid field) -> dropped + WARNING, no exception.

This closes the gap flagged by the kaiju-reviewer on task 0002: the book math
was unit-tested, but the runner branch that parses the wire and feeds it was not.
"""
import logging

import pytest

from kaiju.execution.paper_sim import PaperBook
from kaiju.runner import _apply_orderbook_delta

MARKET = "KXHIGHNY-26MAY17-B65"


def _seeded_book() -> PaperBook:
    """A PaperBook with MARKET snapshotted: yes 96c x100, no 4c x100."""
    book = PaperBook()
    book.update(MARKET, yes=[[96, 100]], no=[[4, 100]])
    return book


def _delta(**over) -> dict:
    evt = {
        "type": "orderbook_delta",
        "market_ticker": MARKET,
        "side": "yes",
        "price_dollars": "0.96",
        "delta_fp": "-54.00",
    }
    evt.update(over)
    return evt


def test_delta_reduces_level_price_to_cents_and_signed_size():
    """price_dollars '0.96' -> 96c (round, not int); delta_fp '-54.00' -> -54.
    100 - 54 = 46 at 96c; the other side is untouched."""
    book = _seeded_book()
    _apply_orderbook_delta(book, _delta())
    assert book.levels(MARKET, "yes") == {96: 46}
    assert book.levels(MARKET, "no") == {4: 100}


def test_delta_parse_uses_round_not_truncation():
    """0.96 * 100 == 95.99999999999999 in float; the parse must round to 96.
    A regression to int()/truncation would write the level at 95c and fail here."""
    book = _seeded_book()
    _apply_orderbook_delta(book, _delta(price_dollars="0.96", delta_fp="-1.00"))
    assert 96 in book.levels(MARKET, "yes")
    assert 95 not in book.levels(MARKET, "yes")


def test_delta_adds_new_positive_level():
    """A positive delta_fp at a fresh price adds a level (signed-add path)."""
    book = _seeded_book()
    _apply_orderbook_delta(
        book, _delta(side="no", price_dollars="0.05", delta_fp="30.00")
    )
    assert book.levels(MARKET, "no") == {4: 100, 5: 30}


def test_delta_removing_full_size_drops_level():
    """A delta that drives the level to 0 removes it (never stored negative)."""
    book = PaperBook()
    book.update(MARKET, yes=[[96, 54]], no=[[4, 100]])
    _apply_orderbook_delta(book, _delta(delta_fp="-54.00"))
    assert 96 not in book.levels(MARKET, "yes")


def test_orphan_delta_before_snapshot_drops_and_warns(caplog):
    """A delta for a market with no snapshot must NOT create a phantom level,
    and must log a resync WARNING."""
    book = PaperBook()  # MARKET never snapshotted
    with caplog.at_level(logging.WARNING):
        _apply_orderbook_delta(book, _delta())
    assert book.levels(MARKET, "yes") == {}  # uncorrupted
    assert "before snapshot" in caplog.text


@pytest.mark.parametrize(
    "bad",
    [
        {"side": None},            # missing side
        {"side": "maybe"},         # invalid side
        {"price_dollars": None},   # missing price
        {"delta_fp": None},        # missing delta
    ],
)
def test_malformed_delta_drops_and_warns_without_raising(bad, caplog):
    """A malformed delta (missing/invalid field) is dropped with a WARNING and
    never raises — the book is left exactly as seeded."""
    book = _seeded_book()
    evt = _delta()
    for k, v in bad.items():
        if v is None:
            evt.pop(k, None)
        else:
            evt[k] = v
    with caplog.at_level(logging.WARNING):
        _apply_orderbook_delta(book, evt)  # must not raise
    assert book.levels(MARKET, "yes") == {96: 100}
    assert book.levels(MARKET, "no") == {4: 100}
    assert "malformed orderbook_delta dropped" in caplog.text
