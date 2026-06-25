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
    """The parse must ROUND price dollars to cents, not truncate. 0.29 * 100 ==
    28.999999999999996 in float, so round() -> 29 but int() -> 28 (verified on
    this build; 0.96 does NOT distinguish them — both give 96). A positive delta
    at 0.29 must grow the 29c level; a regression to int()/truncation would
    instead create a phantom 28c level and leave 29c untouched, failing BOTH
    assertions below."""
    book = PaperBook()
    book.update(MARKET, yes=[[29, 100]], no=[[4, 100]])
    _apply_orderbook_delta(book, _delta(price_dollars="0.29", delta_fp="30.00"))
    assert book.levels(MARKET, "yes") == {29: 130}  # round -> 29c: 100 + 30
    assert 28 not in book.levels(MARKET, "yes")      # truncation would land here


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
    """A delta rejected by the presence/side guard (side not in {yes,no}, or an
    absent price_dollars/delta_fp) is dropped with a WARNING and does NOT raise —
    the book is left exactly as seeded. (A present-but-non-numeric numeric field
    takes the parse-error path instead — see the next test.)"""
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


@pytest.mark.parametrize(
    "bad",
    [
        {"price_dollars": "abc"},          # non-numeric price string -> ValueError
        {"price_dollars": "0.9x"},         # partially-numeric price -> ValueError
        {"delta_fp": "not-a-number"},      # non-numeric size string -> ValueError
        {"delta_fp": ["x"]},               # wrong type entirely -> TypeError
    ],
)
def test_nonnumeric_delta_field_drops_and_warns_without_raising(bad, caplog):
    """Task 0006: a present-but-non-numeric price_dollars/delta_fp passes the
    presence guard but cannot be parsed. It must be dropped with the same
    'malformed orderbook_delta dropped' WARNING, NOT raise. A raise would escape
    _on_ws_event, be caught by WsClient.run_forever as a connection error, and
    bounce the ENTIRE WS connection (full reconnect + re-snapshot of every
    market) over one bad field — a large over-reaction to malformed wire data."""
    book = _seeded_book()
    with caplog.at_level(logging.WARNING):
        _apply_orderbook_delta(book, _delta(**bad))  # must not raise
    assert book.levels(MARKET, "yes") == {96: 100}  # unmutated
    assert book.levels(MARKET, "no") == {4: 100}
    assert "malformed orderbook_delta dropped" in caplog.text
