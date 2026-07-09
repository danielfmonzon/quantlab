"""Risk engine: limits, containment, kill switch, and state persistence.

Operates on weights and portfolio state only. No live/paper order logic lives
here — paper-trading integration comes in a later batch.
"""
