"""Experimental per-spool motion ledger; not connected to a printer yet.

An instrumented producer must send EVERY extrusion motion in order, with the
physical spool identity captured at that motion. Length is commanded movement,
not a scale measurement. Any gap, unknown identity or conversion invalidates
the whole result; a partial ledger must never be committed to inventory.
"""
import math


class UsageEvidenceError(ValueError):
    pass


class MotionLedger:
    def __init__(self, job_id):
        if not isinstance(job_id, str) or not job_id:
            raise UsageEvidenceError("A printer job identity is required")
        self.job_id = job_id
        self.next_sequence = 0
        self.grams = {}
        self.invalid = None
        self.finished = False

    def _fail(self, message):
        if self.invalid is None:
            self.invalid = message
        raise UsageEvidenceError(message)

    def record(self, sequence, head, spool_id, delta_mm, flow_factor, grams_per_mm):
        if self.finished:
            self._fail("A motion arrived after the job finished")
        if self.invalid:
            raise UsageEvidenceError(self.invalid)
        if type(sequence) is not int or sequence != self.next_sequence:
            self._fail("The motion event stream has a gap or duplicate")
        if type(head) is not int or not 0 <= head < 4:
            self._fail("The physical head is unknown")
        if not isinstance(spool_id, str) or not spool_id:
            self._fail("The physical spool identity is unknown")
        values = (delta_mm, flow_factor, grams_per_mm)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            self._fail("Motion or material conversion is invalid")
        if flow_factor <= 0 or grams_per_mm <= 0:
            self._fail("Flow and material conversion must be positive")
        # The Klipper motion delta already includes the active flow factor.
        # Dividing by it yields nominal G-code length, not commanded physical
        # filament movement; never apply the factor a second time either.
        amount = delta_mm * grams_per_mm
        if not math.isfinite(amount):
            self._fail("Motion conversion overflowed")
        key = (head, spool_id)
        self.grams[key] = self.grams.get(key, 0.0) + amount
        self.next_sequence += 1

    def finish(self, expected_next_sequence, *, completed, continuous, confirmed_spools):
        if self.finished:
            self._fail("The motion ledger was already finished")
        self.finished = True
        if self.invalid:
            raise UsageEvidenceError(self.invalid)
        if type(expected_next_sequence) is not int or expected_next_sequence != self.next_sequence or not self.next_sequence:
            self._fail("The motion event stream is incomplete")
        if completed is not True or continuous is not True or confirmed_spools is not True:
            self._fail("Completion, uninterrupted capture and spool identity must be confirmed")
        totals = {}
        for (_, spool_id), amount in self.grams.items():
            if not math.isfinite(amount) or amount < -1e-8:
                self._fail("The net motion for a spool is invalid")
            totals[spool_id] = totals.get(spool_id, 0.0) + max(0.0, amount)
        return {spool: round(amount, 3) for spool, amount in totals.items()}
